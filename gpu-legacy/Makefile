# POSIX / FreeBSD Makefile for gpu-legacy
CC ?= clang
CFLAGS ?= -O2 -Wall -Wextra -I.
LDADD ?= -lm

TARGET = run
OBJS = sm11_shim.o run.o

all: $(TARGET)

sm11_shim.o: sm11_shim.c sm11_shim.h sm11_compat.h
	$(CC) $(CFLAGS) -c sm11_shim.c -o $@

run.o: run.c sm11_shim.h
	$(CC) $(CFLAGS) -c run.c -o $@

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LDFLAGS) $(LDADD)

clean:
	rm -f $(TARGET) *.o

.PHONY: all clean
