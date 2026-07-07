/* Minimal STREAM-triad memory-bandwidth benchmark (OpenMP).
 *
 * Phase 0 needs the box's REAL achievable DRAM bandwidth, not the nameplate:
 * every MoE CPU-offload tok/s estimate in the architectural plan chains off it,
 * and dmidecode (nameplate DIMM speed) needs sudo anyway. STREAM measures what
 * the memory subsystem actually delivers under a bandwidth-bound kernel.
 *
 * Arrays are sized well past the Threadripper 3960X's 128 MB L3 so we measure
 * DRAM, not cache. Reports best-of-N triad bandwidth in GB/s.
 *
 * Build: gcc -O3 -fopenmp -march=native stream.c -o stream
 * Run:   OMP_NUM_THREADS=24 OMP_PROC_BIND=spread OMP_PLACES=cores ./stream
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#ifndef N
#define N 200000000L   /* 200M doubles/array = 1.6 GB/array, 4.8 GB total */
#endif
#ifndef NTIMES
#define NTIMES 10
#endif

int main(void) {
    const double scalar = 3.0;
    double best = 1e30;
    long j;

    /* heap, not .bss — 4.8 GB of static arrays overflow the default code model */
    double *a = malloc(N * sizeof(double));
    double *b = malloc(N * sizeof(double));
    double *c = malloc(N * sizeof(double));
    if (!a || !b || !c) { perror("malloc"); return 1; }

    #pragma omp parallel for
    for (j = 0; j < N; j++) { a[j] = 1.0; b[j] = 2.0; c[j] = 0.0; }

    int nthreads = 0;
    #pragma omp parallel
    { if (omp_get_thread_num() == 0) nthreads = omp_get_num_threads(); }

    for (int k = 0; k < NTIMES; k++) {
        double t0 = omp_get_wtime();
        #pragma omp parallel for
        for (j = 0; j < N; j++) c[j] = a[j] + scalar * b[j];
        double dt = omp_get_wtime() - t0;
        if (dt < best) best = dt;
    }

    /* Triad reads a,b and writes c => 3 arrays * 8 bytes moved per element. */
    double bytes = 3.0 * sizeof(double) * (double)N;
    double gbps = (bytes / best) / 1e9;
    printf("STREAM triad: N=%ld/array (%.2f GB total), threads=%d\n",
           N, (3.0 * sizeof(double) * (double)N) / 1e9, nthreads);
    printf("best triad time: %.4f s\n", best);
    printf("MEMORY BANDWIDTH: %.1f GB/s\n", gbps);
    /* guard against dead-code elimination */
    if (c[N/2] < 0) printf("unreachable %f\n", c[N/2]);
    return 0;
}
