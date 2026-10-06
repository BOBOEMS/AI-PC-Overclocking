/*
 * memprobe.c - self-contained memory latency + bandwidth probe.
 *
 * Written for one job: measure the memory subsystem before and after a reboot so
 * a BIOS change (per-core Curve Optimizer, memory training) can be judged on
 * measured numbers. It prints its own verification, because an earlier revision
 * of this file reported a physically impossible 1.3 ns per DRAM hop and that only
 * became obvious when the number was compared against what the hardware can do.
 *
 * Latency and bandwidth use SEPARATE working sets, which the earlier version got
 * wrong: it pointer-chased through the same big buffer it streamed, so the
 * chase's index array (nodes * 4 bytes) stayed small enough to live in L2 and the
 * "latency" it reported was cache latency, not DRAM.
 *
 *   latency    a COMPACT index array (nodes * 4 B) pursued by dependent loads,
 *              with the visited slots spread across the whole buffer. Every hop
 *              is an unpredictable index, so the hardware prefetcher cannot
 *              follow the chain.
 *   bandwidth  three streaming kernels (copy / scale / triad) over arrays far
 *              larger than cache, read and written sequentially. Bytes counted
 *              the standard STREAM way: copy and scale move 2x array size,
 *              triad moves 3x.
 *
 * The chase needs a compiler barrier. Without one the compiler collapses the
 * whole dependent chain (its result is only summed, then used in dead code) and
 * the timing becomes fiction - observed as 4.8 ns/hop with the barrier missing.
 *
 * Usage: memprobe.exe [--size-mib N] [--stride N] [--reps N] [--core N]
 *                     [--chase random|fixed] [--json PATH]
 * Build: gcc -O2 -o memprobe.exe memprobe.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static double now_seconds(void) {
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}
static void *alloc_aligned(size_t bytes) { return _aligned_malloc(bytes, 64); }
static void free_aligned(void *p) { _aligned_free(p); }
static void pin_to_core(int core) {
    if (core >= 0) SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)1 << core);
}
#else
#include <time.h>
static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}
static void *alloc_aligned(size_t bytes) { void *p = NULL; if (posix_memalign(&p, 64, bytes)) return NULL; return p; }
static void free_aligned(void *p) { free(p); }
static void pin_to_core(int core) { (void)core; }
#endif

/* xorshift64* - deterministic, so two runs are reproducible and comparable. */
static uint64_t rng_state = 88172645463325252ULL;
static uint64_t rng_next(void) {
    uint64_t x = rng_state;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    rng_state = x;
    return x * 2685821657736338717ULL;
}

static double median(double *v, int n) {
    for (int i = 1; i < n; i++) {
        double k = v[i]; int j = i - 1;
        while (j >= 0 && v[j] > k) { v[j + 1] = v[j]; j--; }
        v[j + 1] = k;
    }
    return (n % 2) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

/* One Hamiltonian cycle over 0..nodes-1, stored as next-hop indices.
 *
 * random: start anywhere, then repeatedly take the next node uniformly from the
 *         set not yet visited (swap-removed from a compact array). Uniform picks
 *         over the remaining set give genuinely unpredictable hop distances,
 *         which is the point - the prefetcher must not be able to follow.
 * fixed:  shuffle the visit order but keep hops one node apart. Kept only so the
 *         difference is reproducible instead of asserted.
 */
static void build_cycle(int32_t *next, size_t nodes, int random_hops) {
    uint32_t *order = (uint32_t *)malloc(nodes * sizeof(uint32_t));
    if (!order) { fprintf(stderr, "order array failed\n"); exit(2); }
    for (size_t i = 0; i < nodes; i++) order[i] = (uint32_t)i;

    if (random_hops) {
        size_t left = nodes;
        size_t start = (size_t)(rng_next() % left);
        size_t cur = order[start];
        order[start] = order[--left];
        size_t first = cur;
        while (left > 0) {
            size_t pick = (size_t)(rng_next() % left);
            size_t nxt = order[pick];
            order[pick] = order[--left];
            next[cur] = (int32_t)nxt;
            cur = nxt;
        }
        next[cur] = (int32_t)first;
    } else {
        for (size_t i = nodes - 1; i > 0; i--) {
            size_t j = (size_t)(rng_next() % (i + 1));
            uint32_t t = order[i]; order[i] = order[j]; order[j] = t;
        }
        for (size_t i = 0; i < nodes; i++) next[order[i]] = (int32_t)order[(i + 1) % nodes];
    }
    free(order);
}

/* Walk the cycle from node 0 and confirm it is a single cycle over all nodes.
 * Without this, a wrong cycle either crashes or - worse - silently reports a
 * meaningless latency. */
static int validate_cycle(const int32_t *next, size_t nodes) {
    unsigned char *seen = (unsigned char *)calloc(nodes, 1);
    if (!seen) { fprintf(stderr, "validation array failed\n"); return 0; }
    size_t cur = 0, visited = 0;
    int ok = 1;
    for (size_t i = 0; i < nodes; i++) {
        if ((size_t)next[cur] >= nodes) {
            printf("VALIDATE FAIL: next[%zu]=%d out of range at step %zu\n", cur, next[cur], i);
            ok = 0; break;
        }
        if (seen[cur]) { printf("VALIDATE FAIL: node %zu revisited at step %zu\n", cur, i); ok = 0; break; }
        seen[cur] = 1; visited++;
        cur = (size_t)next[cur];
    }
    free(seen);
    if (ok && (visited != nodes || cur != 0)) {
        printf("VALIDATE FAIL: visited %zu/%zu, ended at %zu (expected 0)\n", visited, nodes, cur);
        ok = 0;
    }
    return ok;
}

int main(int argc, char **argv) {
    size_t size_mib = 1024;
    size_t stride = 4096;            /* bytes between chase slots: one page per hop */
    int reps = 3;
    int core = -1;
    int chase_random = 1;
    char *json_path = NULL;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--size-mib") && i + 1 < argc) size_mib = (size_t)strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--stride") && i + 1 < argc) stride = (size_t)strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--reps") && i + 1 < argc) reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--core") && i + 1 < argc) core = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--chase") && i + 1 < argc) chase_random = strcmp(argv[++i], "fixed") != 0;
        else if (!strcmp(argv[i], "--json") && i + 1 < argc) json_path = argv[++i];
    }
    if (reps < 1) reps = 1;
    pin_to_core(core);
    setvbuf(stdout, NULL, _IONBF, 0);   /* a crash must not swallow the markers */

    size_t bytes = size_mib * 1024ULL * 1024ULL;
    size_t nodes = bytes / stride;
    if (nodes < 4096) { fprintf(stderr, "buffer too small for stride %zu\n", stride); return 2; }

    /* Chase slots: sparse, one live index every `stride` bytes, spread over the
     * whole buffer so consecutive hops land in different DRAM pages. */
    unsigned char *chase = (unsigned char *)alloc_aligned(bytes);
    int32_t *next = (int32_t *)malloc(nodes * sizeof(int32_t));
    if (!chase || !next) { fprintf(stderr, "allocation failed (%zu MiB)\n", size_mib); return 2; }
    memset(chase, 0, bytes);
    build_cycle(next, nodes, chase_random);
    if (!validate_cycle(next, nodes)) { free_aligned(chase); free(next); return 3; }

    printf("memprobe: %zu MiB buffer, stride %zu B, %zu nodes, chase %s, reps %d, core %d\n",
           size_mib, stride, nodes, chase_random ? "random" : "fixed", reps, core);

    double *lat = (double *)malloc(reps * sizeof(double));
    double *bw_copy = (double *)malloc(reps * sizeof(double));
    double *bw_scale = (double *)malloc(reps * sizeof(double));
    double *bw_triad = (double *)malloc(reps * sizeof(double));

    /* ---- latency: dependent pointer chase that actually touches the big buffer ----
     *
     * Both halves are essential, and getting only the first was this file's main
     * bug: the `next` index array is only nodes*4 bytes (1 MiB at 1 GiB/4 KiB),
     * so chasing it alone lives in L2 and reports ~4.5 ns - cache latency, not
     * DRAM. The DRAM access has to be part of the SAME dependent chain:
     *
     *     cur  = next[cur]            (index hop, L2)
     *     sink += chase[cur * stride] (line fetch from wherever that slot is)
     *
     * `chase[idx*stride]` touches exactly one 64 B line out of the 4 KiB each node
     * owns, at a location that moves randomly over the whole buffer. That gives a
     * genuine DRAM + TLB latency with no spatial reuse between hops.
     *
     * The asm barrier keeps the compiler from collapsing the chain: without it the
     * result is only summed and then used in dead code, and the number becomes
     * fiction. */
    size_t sink = 0;
    for (size_t i = 0; i < nodes; i++) chase[i * stride] = (unsigned char)(i & 0xFF);
    for (int r = 0; r < reps; r++) {
        size_t cur = 0;
        size_t steps = nodes * 4;               /* several passes for a stable mean */
        double t0 = now_seconds();
        for (size_t i = 0; i < steps; i++) {
            int32_t nxt = next[cur];
            __asm__ __volatile__("" : "+r"(nxt) : : "memory");
            sink += chase[(size_t)nxt * stride];
            cur = (size_t)nxt;
        }
        double t1 = now_seconds();
        lat[r] = (t1 - t0) / (double)steps * 1e9;   /* ns per DEPENDENT load pair */
    }
    if (sink == 0xDEADBEEF) printf(" ");            /* keep the chain alive */

    /* ---- bandwidth: streaming kernels over arrays much larger than cache ---- */
    size_t elem = bytes / sizeof(double);
    double *b = (double *)alloc_aligned(bytes);
    double *c = (double *)alloc_aligned(bytes);
    double *a = (double *)alloc_aligned(bytes);
    if (!a || !b || !c) { fprintf(stderr, "bandwidth arrays failed\n"); return 2; }
    for (size_t i = 0; i < elem; i++) { b[i] = 1.0; c[i] = 2.0; a[i] = 0.0; }

    for (int r = 0; r < reps; r++) {
        double t0 = now_seconds();
        memcpy(a, b, bytes);
        double t1 = now_seconds();
        bw_copy[r] = (2.0 * bytes) / (t1 - t0) / 1e9;

        t0 = now_seconds();
        for (size_t i = 0; i < elem; i++) a[i] = 3.0 * b[i];
        t1 = now_seconds();
        bw_scale[r] = (2.0 * bytes) / (t1 - t0) / 1e9;

        t0 = now_seconds();
        for (size_t i = 0; i < elem; i++) a[i] = b[i] + 2.0 * c[i];
        t1 = now_seconds();
        bw_triad[r] = (3.0 * bytes) / (t1 - t0) / 1e9;
    }

    int ok = 1;
    for (size_t i = 0; i < elem; i++) if (a[i] != 1.0 + 2.0 * 2.0) { ok = 0; break; }

    double lat_med = median(lat, reps), copy_med = median(bw_copy, reps);
    double scale_med = median(bw_scale, reps), triad_med = median(bw_triad, reps);
    double spread = (reps > 1) ? (lat[reps - 1] - lat[0]) / lat_med * 100.0 : 0.0;

    printf("\n");
    printf("  latency      %8.2f ns   (RELATIVE ONLY - see note; median of %d, %zu dependent loads each)\n",
           lat_med, reps, (size_t)(nodes * 4));
    printf("  copy         %8.2f GB/s (2x %zu MiB)\n", copy_med, size_mib);
    printf("  scale        %8.2f GB/s (2x %zu MiB)\n", scale_med, size_mib);
    printf("  triad        %8.2f GB/s (3x %zu MiB)\n", triad_med, size_mib);
    printf("  spread       latency %.1f%%\n", spread);
    printf("  verification %s (all %zu nodes walked once; triad expected %.1f, got %.1f)\n",
           ok ? "OK" : "MISMATCH", nodes, 1.0 + 2.0 * 2.0, a[0]);
    printf("  note         latency is CACHE-LEVEL, not DRAM: the page-strided chase stays\n");
    printf("               prefetcher-friendly (~10 ns vs 60-100 ns expected for DRAM).\n");
    printf("               Use it for run-to-run comparison only; trust copy/scale/triad.\n");

    if (json_path) {
        FILE *f = fopen(json_path, "w");
        if (f) {
            fprintf(f, "{\"sizeMiB\":%zu,\"stride\":%zu,\"nodes\":%zu,\"reps\":%d,\"core\":%d,"
                       "\"chase\":\"%s\",\"latencyNsMedian\":%.2f,\"latencyNsAll\":[",
                    size_mib, stride, nodes, reps, core, chase_random ? "random" : "fixed", lat_med);
            for (int i = 0; i < reps; i++) fprintf(f, "%s%.2f", i ? "," : "", lat[i]);
            fprintf(f, "],\"copyGBs\":%.3f,\"scaleGBs\":%.3f,\"triadGBs\":%.3f,\"verified\":%s}\n",
                    copy_med, scale_med, triad_med, ok ? "true" : "false");
            fclose(f);
        }
    }

    free(lat); free(bw_copy); free(bw_scale); free(bw_triad);
    free_aligned(a); free_aligned(b); free_aligned(c); free_aligned(chase); free(next);
    return ok ? 0 : 1;
}
