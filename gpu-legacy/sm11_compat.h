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
#else
#include <dlfcn.h>
#include <sched.h>
#include <unistd.h>
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
#endif

#endif /* SM11_POSIX_COMPAT_H */
