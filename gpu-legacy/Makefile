# POSIX / FreeBSD Makefile for gpu-legacy
CC ?= clang
CFLAGS ?= -O2 -Wall -Wextra
SM11_CPPFLAGS = -I.
OPENMP ?= -fopenmp
LDADD ?= -lm

TARGETS = run bench_matvec bench_batch_scale bench_quant bench_smolshape bench_links

all: $(TARGETS)

sm11_shim.o: sm11_shim.c sm11_shim.h sm11_compat.h
	$(CC) $(CPPFLAGS) $(SM11_CPPFLAGS) $(CFLAGS) $(OPENMP) -c sm11_shim.c -o $@

run.o: run.c sm11_shim.h
	$(CC) $(CPPFLAGS) $(SM11_CPPFLAGS) $(CFLAGS) $(OPENMP) -c run.c -o $@

run: sm11_shim.o run.o
	$(CC) $(CFLAGS) $(OPENMP) -o $@ sm11_shim.o run.o $(LDFLAGS) $(LDADD)

bench_matvec: bench_matvec.c sm11_shim.o sm11_compat.h sm11_shim.h
	$(CC) $(CPPFLAGS) $(SM11_CPPFLAGS) $(CFLAGS) $(OPENMP) -o $@ bench_matvec.c sm11_shim.o $(LDFLAGS) $(LDADD)

bench_batch_scale: bench_batch_scale.c sm11_shim.o sm11_compat.h sm11_shim.h
	$(CC) $(CPPFLAGS) $(SM11_CPPFLAGS) $(CFLAGS) $(OPENMP) -o $@ bench_batch_scale.c sm11_shim.o $(LDFLAGS) $(LDADD)

bench_quant: bench_quant.c sm11_shim.o sm11_compat.h sm11_shim.h
	$(CC) $(CPPFLAGS) $(SM11_CPPFLAGS) $(CFLAGS) $(OPENMP) -o $@ bench_quant.c sm11_shim.o $(LDFLAGS) $(LDADD)

bench_smolshape: bench_smolshape.c sm11_shim.o sm11_compat.h sm11_shim.h
	$(CC) $(CPPFLAGS) $(SM11_CPPFLAGS) $(CFLAGS) $(OPENMP) -o $@ bench_smolshape.c sm11_shim.o $(LDFLAGS) $(LDADD)

bench_links: bench_links.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ bench_links.c $(LDFLAGS)

clean:
	rm -f $(TARGETS) *.o

.PHONY: all clean
