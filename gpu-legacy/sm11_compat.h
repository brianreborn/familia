/* POSIX abstraction for sm11 legacy GPU shim */
#ifndef SM11_POSIX_COMPAT_H
#define SM11_POSIX_COMPAT_H

#ifdef _WIN32
#include <windows.h>
#define SM11_API __stdcall
typedef HMODULE sm11_lib_t;
#define sm11_dlopen(name) LoadLibraryA(name)
#define sm11_dlsym(handle, sym) GetProcAddress((HMODULE)(handle), sym)
#define sm11_dlclose(handle) FreeLibrary((HMODULE)(handle))
#define sm11_yield() YieldProcessor()
static inline double sm11_time_ms(void) {
    static LARGE_INTEGER f;
    static int init = 0;
    LARGE_INTEGER c;
    if (!init) { QueryPerformanceFrequency(&f); init = 1; }
    QueryPerformanceCounter(&c);
    return 1000.0 * (double)c.QuadPart / (double)f.QuadPart;
}
#else
#include <dlfcn.h>
#include <sched.h>
#include <unistd.h>
#include <time.h>
#define SM11_API
typedef void* sm11_lib_t;
#define sm11_dlopen(name) dlopen(name, RTLD_NOW)
#define sm11_dlsym(handle, sym) dlsym(handle, sym)
#define sm11_dlclose(handle) dlclose(handle)
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#define sm11_yield() __asm__ volatile("pause")
#else
#define sm11_yield() sched_yield()
#endif
static inline double sm11_time_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1000.0 + (double)ts.tv_nsec / 1000000.0;
}
#endif

#endif /* SM11_POSIX_COMPAT_H */
