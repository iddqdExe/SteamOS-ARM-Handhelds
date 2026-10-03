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

static int menu_on_top(Display *d, Window root, Window steam) {
    Window r, parent, *children = NULL; unsigned int count = 0;
    if (!XQueryTree(d, root, &r, &parent, &children, &count)) return 0;
    int top = count && children[count - 1] == steam;
    if (children) XFree(children);
    return top;
}

static int menu_still_on_top(Display *d, Window root, Window steam) {
    Window focus; int revert; XGetInputFocus(d, &focus, &revert);
    return menu_on_top(d, root, steam) && focus == steam;
}

static int overlay_scenario(Display *d, Window root, Window game, Window steam,
                            Atom app, Atom wm, int mode) {
    Atom gfx = XInternAtom(d, "GAMESCOPE_FOCUSED_APP_GFX", False);
    Atom game_id = XInternAtom(d, "STEAM_GAME", False);
    Atom overlay = XInternAtom(d, "STEAM_OVERLAY", False);
    Atom input = XInternAtom(d, "STEAM_INPUT_FOCUS", False);
    property(d, game, game_id, XA_CARDINAL, mode == 7 ? 769 : 123);
    property(d, steam, game_id, XA_CARDINAL, 769);
    property(d, steam, overlay, XA_CARDINAL, mode == 5 ? 0 : 1);
    property(d, steam, input, XA_CARDINAL, 1);
    property(d, root, gfx, XA_CARDINAL, mode == 6 ? 456 : 123);
    property(d, root, app, XA_CARDINAL, 769);
    if (mode == 8) XUnmapWindow(d, steam);
    XSync(d, False);
    usleep(900000);
    if (mode >= 5 && mode <= 8) {
        if (state(d, game, wm) != 3) { fprintf(stderr, "restored without valid visible game overlay\n"); return 1; }
        return 0;
    }
    if (state(d, game, wm) != 1) { fprintf(stderr, "game remained minimized behind active QAM\n"); return 1; }
    if (!menu_still_on_top(d, root, steam)) { fprintf(stderr, "restore stole menu focus or stacking\n"); return 1; }
    if (mode == 3) return 0;
    if (mode == 9) {
        /* Gamescope's focused app/window can bounce while QAM stays visible. */
        Atom win = XInternAtom(d, "GAMESCOPE_FOCUSED_WINDOW", False);
        property(d, root, app, XA_CARDINAL, 123);
        property(d, root, win, XA_CARDINAL, None);
        usleep(350000);
        property(d, root, win, XA_CARDINAL, game);
        property(d, root, app, XA_CARDINAL, 769);
        property(d, game, wm, wm, 3);
        usleep(2600000);
        if (state(d, game, wm) != 3 || !menu_still_on_top(d, root, steam)) {
            fprintf(stderr, "focus bounce rearmed the same continuous overlay\n"); return 1;
        }
        return 0;
    }
    if (mode == 10) {
        /* Wine can minimize again, then report stale Normal before menu close. */
        property(d, game, wm, wm, 3);
        usleep(2600000);
        property(d, game, wm, wm, 1);
        XSelectInput(d, game, PropertyChangeMask);
        property(d, steam, input, XA_CARDINAL, 0);
        property(d, root, app, XA_CARDINAL, 123);
        XSetInputFocus(d, game, RevertToParent, CurrentTime); XSync(d, False);
        int events = 0;
        for (int i = 0; i < 40; i++) {
            usleep(50000);
            while (XPending(d)) { XEvent e; XNextEvent(d, &e); if (e.type == PropertyNotify && e.xproperty.atom == wm) events++; }
            if (state(d, game, wm) == 1 && events >= 2) break;
        }
        if (state(d, game, wm) != 1 || events < 2) {
            fprintf(stderr, "subsequent minimization lost post-overlay fallback (%d events)\n", events); return 1;
        }
        return 0;
    }
    if (mode == 11 || mode == 12 || mode == 13) {
        property(d, game, wm, wm, 3);
        usleep(2600000);
        if (mode == 12) {
            property(d, game, wm, wm, 1);
            property(d, steam, input, XA_CARDINAL, 0);
        }
        XSelectInput(d, game, PropertyChangeMask);
        property(d, root, app, XA_CARDINAL, 123);
        XSetInputFocus(d, game, RevertToParent, CurrentTime); XSync(d, False);
        int activated = 0, reopened = 0;
        Atom protocols = XInternAtom(d, "WM_PROTOCOLS", False);
        Atom take = XInternAtom(d, "WM_TAKE_FOCUS", False);
        for (int i = 0; i < 100; i++) {
            usleep(10000);
            while (XPending(d)) {
                XEvent e; XNextEvent(d, &e);
                if (e.type == ClientMessage && e.xclient.message_type == protocols
                    && (Atom)e.xclient.data.l[0] == take) activated++;
                if (mode == 12 && !reopened && e.type == PropertyNotify
                    && e.xproperty.atom == wm && state(d, game, wm) == 3) {
                    /* Reopen during the old fallback's 100 ms delay, while
                     * gamescope/X focus still temporarily report the game. */
                    property(d, steam, input, XA_CARDINAL, 1);
                    reopened = 1;
                }
            }
        }
        if (mode == 12 && !reopened) { fprintf(stderr, "fallback delay was not exercised\n"); return 1; }
        if (mode == 13) {
            if (state(d, game, wm) != 3 || activated || !menu_on_top(d, root, steam)) {
                fprintf(stderr, "active overlay did not block restore/activation\n"); return 1;
            }
            property(d, steam, input, XA_CARDINAL, 0);
            for (int i = 0; i < 150; i++) {
                usleep(10000);
                while (XPending(d)) {
                    XEvent e; XNextEvent(d, &e);
                    if (e.type == ClientMessage && e.xclient.message_type == protocols
                        && (Atom)e.xclient.data.l[0] == take) activated++;
                }
            }
            if (state(d, game, wm) != 1 || activated != 1) {
                fprintf(stderr, "menu close lost/duplicated deferred activation (%d activations)\n", activated); return 1;
            }
            return 0;
        }
        XSetInputFocus(d, steam, RevertToParent, CurrentTime); XSync(d, False);
        if (state(d, game, wm) != 3 || activated || !menu_still_on_top(d, root, steam)) {
            fprintf(stderr, "raised/restored/activated game over active overlay (%d activations)\n", activated); return 1;
        }
        return 0;
    }
    property(d, game, wm, wm, 3);
    usleep(2600000);
    if (state(d, game, wm) != 3) { fprintf(stderr, "repeated restore while same menu remained open\n"); return 1; }
    property(d, steam, input, XA_CARDINAL, 0);
    property(d, root, app, XA_CARDINAL, 123);
    usleep(350000);
    property(d, steam, input, XA_CARDINAL, 1);
    property(d, root, app, XA_CARDINAL, 769);
    usleep(900000);
    if (state(d, game, wm) != 1 || !menu_still_on_top(d, root, steam)) {
        fprintf(stderr, "restore did not rearm for a new QAM opening\n"); return 1;
    }
    return 0;
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
    if (atoi(argv[2]) >= 3) return overlay_scenario(d, root, game, steam, app, wm, atoi(argv[2]));
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
