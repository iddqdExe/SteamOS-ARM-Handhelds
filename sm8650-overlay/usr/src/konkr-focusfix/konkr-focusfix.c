/*
 * konkr-focusfix — give games their controls back after the Steam overlay.
 *
 * Opening Quick Access / the Steam menu moves X focus to Steam's window;
 * closing it moves focus back to the game, but Proton's winex11 never
 * re-activates the game (no WM_TAKE_FOCUS), so games that ignore input while
 * inactive stay dead until a click (touchscreen) activates them.
 * This watches the X focus on gamescope's Xwayland and, whenever it returns
 * to the window gamescope has focused (a game, not Steam), repeats what a
 * window manager would do for a WM_TAKE_FOCUS client: send it WM_TAKE_FOCUS.
 * Games in exclusive fullscreen also minimize themselves (WM_STATE Iconic)
 * when the overlay takes focus and never come back: the screen stays black or
 * shows a tiny frozen frame (GTA IV). Remember a game that went Iconic and,
 * once focus is back on it, put WM_STATE through Iconic -> Normal: Wine only
 * restores on that change, and by the time Quick Access closes WM_STATE can
 * already read Normal again with the game still minimized inside Wine.
 *
 * UP-01 adaptation of hashtagbasit/4a12b4, 2026-10-02: recheck focus
 * after the Wine restore delay; never raise a game over a reopened QAM.
 * RP6 fullscreen diagnosis, 2026-10-03: acknowledge Normal once behind a
 * verified active Steam overlay, without mapping, raising or activating it.
 * Wine's minimized client otherwise renders a tiny image inside the unchanged
 * fullscreen buffer. Keep the existing post-overlay restore as a fallback.
 *
 *   konkr-focusfix [:0]
 * Build: cc -O2 -o konkr-focusfix konkr-focusfix.c -lX11
 */
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#define STEAM_APPID 769
/* At most one WM_TAKE_FOCUS per this many seconds: when focus bounces
 * between a game and Steam (GTA IV + Social Club opening Quick Access,
 * three bounces in 14 s), re-activating on every return can keep it going. */
#define MIN_INTERVAL_S 3
/* Restore a minimized game at most this often, so one that keeps minimizing
 * itself can't turn this into a loop. */
#define RESTORE_INTERVAL_S 2
#define NORMAL_STATE 1
#define ICONIC_STATE 3

static double now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

static unsigned long card(Display *d, Window w, Atom a)
{
	Atom t; int f; unsigned long n, r, v = 0; unsigned char *p = NULL;
	if (XGetWindowProperty(d, w, a, 0, 1, False, AnyPropertyType, &t, &f, &n, &r, &p) == Success
	    && p && n && f == 32)
		v = *(unsigned long *)p;
	if (p)
		XFree(p);
	return v;
}

/* First field of WM_STATE (ICCCM): 1 Normal, 3 Iconic. */
static long wm_state(Display *d, Window w, Atom a)
{
	Atom t; int f; unsigned long n, r; unsigned char *p = NULL; long v = -1;
	if (XGetWindowProperty(d, w, a, 0, 2, False, a, &t, &f, &n, &r, &p) == Success
	    && p && n && f == 32)
		v = ((long *)p)[0];
	if (p)
		XFree(p);
	return v;
}

static int is_steam_overlay(Display *d, Window window, Atom game_atom,
                            Atom overlay_atom, Atom input_atom)
{
	XWindowAttributes attributes;
	return window && card(d, window, game_atom) == STEAM_APPID
	    && card(d, window, overlay_atom) == 1
	    && card(d, window, input_atom) == 1
	    && XGetWindowAttributes(d, window, &attributes)
	    && attributes.map_state == IsViewable;
}

static Window active_steam_overlay(Display *d, Window root, Atom game_atom,
                                   Atom overlay_atom, Atom input_atom)
{
	Window returned_root, parent, *children = NULL;
	unsigned int count = 0;
	Window found = None;
	if (!XQueryTree(d, root, &returned_root, &parent, &children, &count))
		return 0;
	for (unsigned int i = 0; i < count; i++) {
		if (is_steam_overlay(d, children[i], game_atom, overlay_atom, input_atom)) {
			found = children[i];
			break;
		}
	}
	if (children)
		XFree(children);
	return found;
}

static int ignore_errors(Display *d, XErrorEvent *e) { (void)d; (void)e; return 0; }

int main(int argc, char **argv)
{
	const char *name = argc > 1 ? argv[1] : NULL;
	Display *d;
	while (!(d = XOpenDisplay(name)))
		sleep(2);
	XSetErrorHandler(ignore_errors);   /* game windows come and go */
	Window root = DefaultRootWindow(d);
	Atom gs_win = XInternAtom(d, "GAMESCOPE_FOCUSED_WINDOW", False);
	Atom gs_app = XInternAtom(d, "GAMESCOPE_FOCUSED_APP", False);
	Atom gs_gfx = XInternAtom(d, "GAMESCOPE_FOCUSED_APP_GFX", False);
	Atom steam_game = XInternAtom(d, "STEAM_GAME", False);
	Atom steam_overlay = XInternAtom(d, "STEAM_OVERLAY", False);
	Atom steam_input = XInternAtom(d, "STEAM_INPUT_FOCUS", False);
	Atom proto = XInternAtom(d, "WM_PROTOCOLS", False);
	Atom take = XInternAtom(d, "WM_TAKE_FOCUS", False);
	Atom wm_state_atom = XInternAtom(d, "WM_STATE", False);
	double restored_at = -RESTORE_INTERVAL_S;
	Window iconic_seen = None;   /* game window seen Iconic since its last restore */
	Window overlay_restored = None; /* at most once per continuous overlay opening */
	Window restoring_overlay = None; /* lifetime follows the visible overlay, not focus bounces */
	Window last = None;
	double sent_at = -MIN_INTERVAL_S;

	for (;;) {
		usleep(250 * 1000);
		Window focus; int rev;
		XGetInputFocus(d, &focus, &rev);
		Window game = card(d, root, gs_win);
		unsigned long app = card(d, root, gs_app);
		if (restoring_overlay
		    && !is_steam_overlay(d, restoring_overlay, steam_game, steam_overlay, steam_input)) {
			overlay_restored = None;
			restoring_overlay = None;
		}
		if (game && app == STEAM_APPID && overlay_restored == None
		    && wm_state(d, game, wm_state_atom) == ICONIC_STATE
		    && now() - restored_at >= RESTORE_INTERVAL_S) {
			unsigned long game_app = card(d, game, steam_game);
			Window overlay = None;
			if (game_app && game_app != STEAM_APPID
			    && card(d, root, gs_gfx) == game_app
			    && card(d, focus, steam_game) == STEAM_APPID
			    && (overlay = active_steam_overlay(d, root, steam_game, steam_overlay, steam_input))) {
				Window current_focus; int current_revert;
				XGetInputFocus(d, &current_focus, &current_revert);
				if (current_focus == focus && card(d, root, gs_win) == game
				    && card(d, root, gs_app) == STEAM_APPID
				    && card(d, root, gs_gfx) == game_app
				    && is_steam_overlay(d, overlay, steam_game, steam_overlay, steam_input)
				    && wm_state(d, game, wm_state_atom) == ICONIC_STATE) {
					long st[2] = { NORMAL_STATE, None };
					overlay_restored = game;
					restoring_overlay = overlay;
					restored_at = now();
					if (iconic_seen == game)
						iconic_seen = None;
					XChangeProperty(d, game, wm_state_atom, wm_state_atom, 32,
					                PropModeReplace, (unsigned char *)st, 2);
					XFlush(d);
					fprintf(stderr, "konkr-focusfix: restored behind Steam overlay 0x%lx (app %lu)\n", game, game_app);
				}
			}
		}
		/* A second minimization during the same overlay is left alone, but
		 * must still arm the old stale-Normal fallback when focus returns. */
		if (game && ((app && app != STEAM_APPID)
		             || (restoring_overlay && overlay_restored == game))
		    && wm_state(d, game, wm_state_atom) == ICONIC_STATE)
			iconic_seen = game;
		if (game && focus == game && iconic_seen == game && app && app != STEAM_APPID
		    && now() - restored_at >= RESTORE_INTERVAL_S
		    && !active_steam_overlay(d, root, steam_game, steam_overlay, steam_input)) {
			long st[2] = { ICONIC_STATE, None };
			if (wm_state(d, game, wm_state_atom) != ICONIC_STATE) {
				XChangeProperty(d, game, wm_state_atom, wm_state_atom, 32,
				                PropModeReplace, (unsigned char *)st, 2);
				XFlush(d);
				usleep(100 * 1000);
			}
			XGetInputFocus(d, &focus, &rev);
			if (focus != game || card(d, root, gs_win) != game
			    || card(d, root, gs_app) != app
			    || active_steam_overlay(d, root, steam_game, steam_overlay, steam_input))
				continue;
			restored_at = now();
			iconic_seen = None;
			st[0] = NORMAL_STATE;
			XChangeProperty(d, game, wm_state_atom, wm_state_atom, 32, PropModeReplace,
			                (unsigned char *)st, 2);
			XMapRaised(d, game);
			XFlush(d);
			fprintf(stderr, "konkr-focusfix: restored minimized 0x%lx (app %lu)\n", game, app);
		}
		/* Do not consume the focus return while the menu still blocks
		 * activation: it may close without another X focus transition. */
		if (game && focus == game
		    && active_steam_overlay(d, root, steam_game, steam_overlay, steam_input))
			continue;
		if (game && focus == game && last != game && last != None
		    && app && app != STEAM_APPID && now() - sent_at >= MIN_INTERVAL_S
		    && !active_steam_overlay(d, root, steam_game, steam_overlay, steam_input)) {
			usleep(100 * 1000);   /* let Steam finish handing focus back */
			/* Steam may have taken focus again meanwhile (Quick Access
			 * opening): then leave it alone. */
			XGetInputFocus(d, &focus, &rev);
			if (focus != game || card(d, root, gs_win) != game
			    || card(d, root, gs_app) != app
			    || active_steam_overlay(d, root, steam_game, steam_overlay, steam_input)) {
				if (focus != game)
					last = focus;
				continue;
			}
			sent_at = now();
			/* WM_TAKE_FOCUS only: Wine then activates the window and sets X focus
			 * itself. Also forcing XSetInputFocus + _NET_ACTIVE_WINDOW made Wine
			 * re-grab/warp the pointer -> endless camera spin in Dying Light. */
			XEvent e = { 0 };
			e.xclient.type = ClientMessage;
			e.xclient.window = game;
			e.xclient.message_type = proto;
			e.xclient.format = 32;
			e.xclient.data.l[0] = take;
			e.xclient.data.l[1] = CurrentTime;
			XSendEvent(d, game, False, NoEventMask, &e);
			XFlush(d);
			fprintf(stderr, "konkr-focusfix: re-activated 0x%lx (app %lu)\n", game, app);
		}
		last = focus;
	}
}
