/* Private runtime mounts keep Python, WebKit helpers and all ELF loaders together.
 * The outer namespace supplies a runtime, not a security boundary. WebKit retains
 * its own inner sandbox. User files and the desktop bus remain available.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <sched.h>
#include <sys/wait.h>
#include <sys/utsname.h>

static void fail(const char *message) {
    fputs(message, stderr);
    fputc('\n', stderr);
    exit(1);
}

static void root_path(char *buffer, size_t size, const char *root, const char *suffix) {
    int length = snprintf(buffer, size, "%s%s", root, suffix);
    if (length < 0 || (size_t)length >= size)
        fail("AppImage runtime path is too long; use a shorter extraction directory.");
}

static char *args[8192];
static size_t count;

static void add(const char *value) {
    if (count >= sizeof(args) / sizeof(args[0]) - 1) {
        fputs("Too many runtime mount arguments.\n", stderr);
        exit(1);
    }
    char *copy = strdup(value);
    if (!copy) fail("Not enough memory to start the AppImage runtime.");
    args[count++] = copy;
}

static void option(const char *name, const char *a, const char *b) {
    add(name); add(a); if (b) add(b);
}

static int reserved(const char *name) {
    const char *names[] = {".", "..", "usr", "etc", "bin", "sbin", "lib", "lib64",
                          "lib32", "proc", "dev", "sys", ".audiobook-host", ".flatpak-info", NULL};
    for (int i = 0; names[i]; i++)
        if (!strcmp(name, names[i])) return 1;
    return 0;
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--diagnose-runtime")) {
        struct utsname system;
        if (uname(&system)) { perror("Read kernel information"); return 1; }
        printf("Kernel: %s %s; architecture: %s\n", system.sysname, system.release, system.machine);
        puts("Build baseline: Arch/CachyOS x86_64; other distributions/CPU baselines require testing.");
        pid_t probe = fork();
        if (probe < 0) { perror("Probe user namespaces"); return 1; }
        if (probe == 0) _exit(unshare(CLONE_NEWUSER) == 0 ? 0 : 2);
        int status;
        while (waitpid(probe, &status, 0) < 0) {
            if (errno != EINTR) { perror("Wait for namespace probe"); return 1; }
        }
        int available = WIFEXITED(status) && WEXITSTATUS(status) == 0;
        puts(available ? "Unprivileged user namespace probe: available" :
             "Unprivileged user namespace probe: unavailable/restricted; this runtime may not launch.");
        puts("No host policy or WebKit sandbox setting was changed. A desktop/session portal and Secret Service are needed for account workflows.");
        return available ? 0 : 2;
    }
    char executable[PATH_MAX], root[PATH_MAX], path[PATH_MAX], lib[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length < 0) { perror("Locate AppImage runtime"); return 1; }
    if ((size_t)length == sizeof(executable) - 1) fail("AppImage executable path is too long.");
    executable[length] = 0;
    strcpy(root, executable);
    char *slash = strrchr(root, '/');
    if (!slash) return 1;
    *slash = 0;
    root_path(lib, sizeof(lib), root, "/usr/lib");
    root_path(path, sizeof(path), root, "/usr/lib/ld-linux-x86-64.so.2");
    add(path);
    add("--inhibit-cache");
    option("--library-path", lib, NULL);
    root_path(path, sizeof(path), root, "/usr/bin/bwrap");
    add(path);
    add("--unshare-user");
    add("--die-with-parent");

    /* Bubblewrap starts with an empty mount root. Directory creation during
     * setup therefore never creates files in the real host's root directory. */
    DIR *directory = opendir("/");
    if (!directory) { perror("Read runtime mount layout"); return 1; }
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        if (reserved(entry->d_name)) continue;
        snprintf(path, sizeof(path), "/%s", entry->d_name);
        option("--bind-try", path, path);
    }
    closedir(directory);
    root_path(path, sizeof(path), root, "/usr");
    option("--ro-bind", path, "/usr");
    root_path(path, sizeof(path), root, "/etc");
    option("--ro-bind", path, "/etc");
    option("--symlink", "usr/bin", "/bin");
    option("--symlink", "usr/bin", "/sbin");
    option("--symlink", "usr/lib", "/lib");
    option("--symlink", "usr/lib", "/lib64");
    option("--proc", "/proc", NULL);
    option("--dev-bind", "/dev", "/dev");
    option("--ro-bind", "/sys", "/sys");

    const char *host_files[] = {"passwd", "group", "hosts", "resolv.conf", "machine-id", "localtime", NULL};
    for (int i = 0; host_files[i]; i++) {
        snprintf(path, sizeof(path), "/etc/%s", host_files[i]);
        if (!access(path, F_OK)) option("--ro-bind", path, path);
    }
    const char *override = getenv("SSL_CERT_FILE");
    if ((!override || !*override) && getenv("AUDIOBOOK_USE_HOST_CA") && !strcmp(getenv("AUDIOBOOK_USE_HOST_CA"), "1")) {
        const char *candidates[] = {"/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem", NULL};
        for (int i = 0; candidates[i]; i++) {
            if (!access(candidates[i], R_OK)) { override = candidates[i]; break; }
        }
        if (!override || !*override) fail("No readable host CA bundle found. Set SSL_CERT_FILE explicitly.");
    }
    const char *extra = getenv("AUDIOBOOK_EXTRA_CA_CERTS");
    if (override && *override) {
        struct stat info;
        if (stat(override, &info) || !S_ISREG(info.st_mode) || !info.st_size || info.st_size > 16 * 1024 * 1024 || access(override, R_OK))
            fail("The explicit CA bundle must be a readable regular certificate file.");
        option("--ro-bind", override, "/etc/ssl/certs/ca-certificates.crt");
        option("--tmpfs", "/usr/share/ca-certificates/trust-source", NULL);
        option("--tmpfs", "/etc/ca-certificates/trust-source", NULL);
        option("--dir", "/etc/ca-certificates/trust-source/anchors", NULL);
        option("--ro-bind", override, "/etc/ca-certificates/trust-source/anchors/selected.pem");
    }
    if (extra && *extra) {
        struct stat info;
        if (stat(extra, &info) || !S_ISREG(info.st_mode) || !info.st_size || info.st_size > 16 * 1024 * 1024 || access(extra, R_OK))
            fail("Additional CA certificates must be a readable regular certificate file.");
        if (!override || !*override) option("--tmpfs", "/etc/ca-certificates/trust-source/anchors", NULL);
        option("--ro-bind", extra, "/etc/ssl/certs/additional-ca.pem");
        option("--ro-bind", extra, "/etc/ca-certificates/trust-source/anchors/additional.pem");
        option("--setenv", "AUDIOBOOK_HAS_EXTRA_CA", "1");
    } else option("--unsetenv", "AUDIOBOOK_HAS_EXTRA_CA", NULL);
    option("--unsetenv", "PYTHONPATH", NULL);
    option("--unsetenv", "LD_LIBRARY_PATH", NULL);
    option("--unsetenv", "LD_PRELOAD", NULL);
    option("--unsetenv", "GTK_PATH", NULL);
    option("--unsetenv", "GTK_MODULES", NULL);
    option("--unsetenv", "GIO_EXTRA_MODULES", NULL);
    option("--unsetenv", "WEBKIT_EXEC_PATH", NULL);
    option("--unsetenv", "WEBKIT_INJECTED_BUNDLE_PATH", NULL);
    option("--unsetenv", "WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS", NULL);
    option("--unsetenv", "WEBKIT_ENABLE_DEBUG_PERMISSIONS_IN_SANDBOX", NULL);
    option("--unsetenv", "WEBKIT_INSPECTOR_SERVER", NULL);
    option("--unsetenv", "FFREPORT", NULL);
    option("--setenv", "PATH", "/usr/bin");
    option("--setenv", "PYTHONHOME", "/usr");
    option("--setenv", "PYTHONNOUSERSITE", "1");
    option("--setenv", "PYTHONDONTWRITEBYTECODE", "1");
    option("--setenv", "GI_TYPELIB_PATH", "/usr/lib/girepository-1.0");
    option("--setenv", "GIO_MODULE_DIR", "/usr/lib/gio/modules");
    option("--setenv", "GIO_USE_PORTALS", "1");
    option("--setenv", "GSETTINGS_SCHEMA_DIR", "/usr/share/glib-2.0/schemas");
    option("--setenv", "XDG_DATA_DIRS", "/usr/share");
    option("--setenv", "FONTCONFIG_FILE", "/etc/fonts/fonts.conf");
    option("--setenv", "SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt");
    option("--setenv", "GST_PLUGIN_SYSTEM_PATH_1_0", "/usr/lib/gstreamer-1.0");
    option("--setenv", "GST_PLUGIN_SCANNER", "/usr/lib/gstreamer-1.0/gst-plugin-scanner");
    option("--setenv", "GST_PLUGIN_PATH_1_0", "");
    option("--setenv", "GDK_PIXBUF_MODULE_FILE", "/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache");
    option("--setenv", "AUDIOBOOK_APPIMAGE", "1");
    /* Use bundled software rendering rather than depending on host GPU drivers. */
    if (!getenv("GSK_RENDERER")) option("--setenv", "GSK_RENDERER", "cairo");
    option("--setenv", "LIBGL_ALWAYS_SOFTWARE", "1");
    option("--setenv", "LIBGL_DRIVERS_PATH", "/usr/lib/dri");
    option("--setenv", "__GLX_VENDOR_LIBRARY_NAME", "mesa");
    option("--setenv", "__EGL_VENDOR_LIBRARY_DIRS", "/usr/share/glvnd/egl_vendor.d");
    add("--");
    add("/usr/bin/python3");
    add("-s");
    add("-B");
    add("/usr/share/audiobook-utility/appimage-entry.py");
    for (int i = 1; i < argc; i++) add(argv[i]);
    args[count] = NULL;
    pid_t child = fork();
    if (child < 0) { perror("Start runtime process"); return 1; }
    if (child == 0) {
        execv(args[0], args);
        int error = errno;
        perror("Start bundled Audiobook Utility runtime");
        _exit(error == ENOENT ? 127 : 1);
    }
    int status;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) { perror("Wait for runtime process"); return 1; }
    }
    int result = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    if (result) fputs("Runtime/application failed. Run this AppImage with --diagnose-runtime for kernel/namespace prerequisites; no security bypass is applied.\n", stderr);
    return result;
}
