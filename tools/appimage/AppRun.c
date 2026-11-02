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

static char *args[8192];
static size_t count;

static void add(const char *value) {
    if (count >= sizeof(args) / sizeof(args[0]) - 1) {
        fputs("Too many runtime mount arguments.\n", stderr);
        exit(1);
    }
    args[count++] = strdup(value);
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
    char executable[PATH_MAX], root[PATH_MAX], path[PATH_MAX], lib[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length < 0) { perror("Locate AppImage runtime"); return 1; }
    executable[length] = 0;
    strcpy(root, executable);
    char *slash = strrchr(root, '/');
    if (!slash) return 1;
    *slash = 0;
    snprintf(lib, sizeof(lib), "%s/usr/lib", root);
    snprintf(path, sizeof(path), "%s/usr/lib/ld-linux-x86-64.so.2", root);
    add(path);
    add("--inhibit-cache");
    option("--library-path", lib, NULL);
    snprintf(path, sizeof(path), "%s/usr/bin/bwrap", root);
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
    snprintf(path, sizeof(path), "%s/usr", root);
    option("--ro-bind", path, "/usr");
    snprintf(path, sizeof(path), "%s/etc", root);
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
    if (argc > 1 && !strcmp(argv[1], "--python")) {
        for (int i = 2; i < argc; i++) add(argv[i]);
    } else {
        add("/usr/share/audiobook-utility/appimage-entry.py");
        for (int i = 1; i < argc; i++) add(argv[i]);
    }
    args[count] = NULL;
    execv(args[0], args);
    perror("Start bundled Audiobook Utility runtime");
    return errno == ENOENT ? 127 : 1;
}
