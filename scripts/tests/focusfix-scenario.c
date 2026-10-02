/* Synthetic X11/QAM scenario: no Steam, Wine or target hardware required. */
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void property(Display *d, Window w, Atom a, Atom type, long value) {
    long values[2] = { value, None };
    XChangeProperty(d, w, a, type, 32, PropModeReplace,
                    (unsigned char *)values, type == XA_CARDINAL ? 1 : 2);
    XSync(d, False);
}
static long state(Display *d, Window w, Atom a) {
    Atom type; int format; unsigned long count, left; unsigned char *data = NULL;
    XGetWindowProperty(d, w, a, 0, 2, False, a, &type, &format, &count, &left, &data);
    long value = data && count ? ((long *)data)[0] : -1;
    if (data) XFree(data);
    return value;
}
int main(int argc, char **argv) {
    (void)argc;
    Display *d = XOpenDisplay(argv[1]);
    if (!d) return 2;
    Window root = DefaultRootWindow(d);
    Window game = XCreateSimpleWindow(d, root, 0, 0, 100, 100, 0, 0, 0);
    Window steam = XCreateSimpleWindow(d, root, 120, 0, 100, 100, 0, 0, 0);
    Atom win = XInternAtom(d, "GAMESCOPE_FOCUSED_WINDOW", False);
    Atom app = XInternAtom(d, "GAMESCOPE_FOCUSED_APP", False);
    Atom wm = XInternAtom(d, "WM_STATE", False);
    XMapWindow(d, game); XMapWindow(d, steam);
    property(d, root, win, XA_CARDINAL, game);
    property(d, root, app, XA_CARDINAL, 123);
    property(d, game, wm, wm, 3);
    XSetInputFocus(d, steam, RevertToParent, CurrentTime); XSync(d, False);
    usleep(700000);  /* let focusfix observe Iconic behind Quick Access */
    if (state(d, game, wm) != 3) { fprintf(stderr, "restored before QAM closed\n"); return 1; }
    if (atoi(argv[2]) == 2) {
        property(d, root, win, XA_CARDINAL, steam);
        property(d, root, app, XA_CARDINAL, 769);
        property(d, steam, wm, wm, 3);
        usleep(700000);
        if (state(d, steam, wm) != 3) { fprintf(stderr, "restored Steam window\n"); return 1; }
        return 0;
    }
    if (atoi(argv[2]) == 1) property(d, game, wm, wm, 1);
    XSelectInput(d, game, PropertyChangeMask);
    XSetInputFocus(d, game, RevertToParent, CurrentTime); XSync(d, False);
    int events = 0;
    for (int i = 0; i < 40; i++) {
        usleep(50000);
        while (XPending(d)) { XEvent e; XNextEvent(d, &e); if (e.type == PropertyNotify && e.xproperty.atom == wm) events++; }
        if (state(d, game, wm) == 1 && events >= (atoi(argv[2]) == 1 ? 2 : 1)) break;
    }
    if (state(d, game, wm) != 1 || events < (atoi(argv[2]) == 1 ? 2 : 1)) {
        fprintf(stderr, "minimized game was not restored (%d property events)\n", events); return 1;
    }
    property(d, game, wm, wm, 3);
    usleep(500000);
    if (state(d, game, wm) != 3) { fprintf(stderr, "restore cooldown missing\n"); return 1; }
    return 0;
}
