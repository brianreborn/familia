# Dual: GNU make (Linux box) builds tools/; FreeBSD bsd.kmod.mk for kmod on angel.
# On angel for the module: make -f Makefile.kmod  (or `make kmod` if bsd.kmod.mk present)

.PHONY: all clean tools kmod depend

CFLAGS ?= -O2 -Wall -Wextra
CFLAGS += -Iinclude

all: tools

tools: tools/nvsoctl

tools/nvsoctl: tools/nvsoctl.c include/nvso.h include/nvso_ioctl.h
	$(CC) $(CFLAGS) -o $@ tools/nvsoctl.c

kmod:
	@if [ -f /usr/share/mk/bsd.kmod.mk ]; then \
	  echo "Use: make -f Makefile.kmod"; \
	  $(MAKE) -f Makefile.kmod; \
	else \
	  echo "nvso: kmod skipped (no bsd.kmod.mk — run Makefile.kmod on FreeBSD angel)"; \
	fi

depend:
	@true

clean:
	rm -f tools/nvsoctl nvso.ko *.o sys/*.o
