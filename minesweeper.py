#!/usr/bin/env python3
"""Terminal Minesweeper - mouse & keyboard driven, resizable, with best-time tracking."""

import json
import os
import random
import sys
import time

try:
    import curses
except ModuleNotFoundError:
    sys.stderr.write(
        "This game requires the 'curses' terminal library, which Windows's "
        "standard Python does not ship.\n"
        "Fix: pip install windows-curses\n"
        "Then run the game again in the same terminal (cmd, PowerShell, or "
        "Windows Terminal).\n"
    )
    sys.exit(1)

SCORES_PATH = os.path.expanduser("~/.minesweeper_scores.json")

DIFFICULTIES = [
    ("Beginner", 9, 9, 10),
    ("Intermediate", 16, 16, 40),
    ("Expert", 16, 30, 99),
    ("Custom", None, None, None),
]

def _enable_windows_console_mouse():
    """On native Windows consoles (cmd.exe/PowerShell), QuickEdit Mode
    intercepts all mouse input for text selection before curses ever sees
    it, silently breaking both clicks and hover. Turn it off and turn on
    mouse reporting so mouse events actually reach the app.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_EXTENDED_FLAGS = 0x0080
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_MOUSE_INPUT = 0x0010

        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS | ENABLE_MOUSE_INPUT
        kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass


CELL_HIDDEN = 0
CELL_REVEALED = 1
CELL_FLAGGED = 2

MINE = -1

# curses may not expose BUTTON5_PRESSED on every build; fall back to the
# well-known bit value used by ncurses for the scroll-down event.
BUTTON5_PRESSED = getattr(curses, "BUTTON5_PRESSED", 0x00200000)


def load_scores():
    try:
        with open(SCORES_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


def save_scores(scores):
    try:
        with open(SCORES_PATH, "w") as f:
            json.dump(scores, f, indent=2)
    except OSError:
        pass


def score_key(rows, cols, mines):
    return f"{rows}x{cols}x{mines}"


def fmt_time(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class Board:
    """Holds mine/flag/reveal state for a rows x cols minefield."""

    def __init__(self, rows, cols, mines):
        self.rows = rows
        self.cols = cols
        self.mines_total = mines
        self.state = [[CELL_HIDDEN] * cols for _ in range(rows)]
        self.is_mine = [[False] * cols for _ in range(rows)]
        self.counts = [[0] * cols for _ in range(rows)]
        self.mines_placed = False
        self.flags_used = 0
        self.revealed_count = 0
        self.exploded = None  # (r, c) of the mine that ended the game

    def neighbors(self, r, c):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    yield nr, nc

    def place_mines(self, safe_r, safe_c):
        forbidden = {(safe_r, safe_c)}
        forbidden.update(self.neighbors(safe_r, safe_c))
        all_cells = [
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if (r, c) not in forbidden
        ]
        n = min(self.mines_total, len(all_cells))
        for r, c in random.sample(all_cells, n):
            self.is_mine[r][c] = True
        for r in range(self.rows):
            for c in range(self.cols):
                if self.is_mine[r][c]:
                    continue
                self.counts[r][c] = sum(
                    1 for nr, nc in self.neighbors(r, c) if self.is_mine[nr][nc]
                )
        self.mines_placed = True

    def toggle_flag(self, r, c):
        s = self.state[r][c]
        if s == CELL_HIDDEN:
            self.state[r][c] = CELL_FLAGGED
            self.flags_used += 1
        elif s == CELL_FLAGGED:
            self.state[r][c] = CELL_HIDDEN
            self.flags_used -= 1

    def reveal(self, r, c):
        """Reveal a cell, flood-filling zeros. Returns False if it was a mine."""
        if self.state[r][c] != CELL_HIDDEN:
            return True
        if not self.mines_placed:
            self.place_mines(r, c)

        if self.is_mine[r][c]:
            self.state[r][c] = CELL_REVEALED
            self.exploded = (r, c)
            return False

        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if self.state[cr][cc] != CELL_HIDDEN:
                continue
            self.state[cr][cc] = CELL_REVEALED
            self.revealed_count += 1
            if self.counts[cr][cc] == 0:
                for nr, nc in self.neighbors(cr, cc):
                    if self.state[nr][nc] == CELL_HIDDEN and not self.is_mine[nr][nc]:
                        stack.append((nr, nc))
        return True

    def chord(self, r, c):
        """Reveal neighbors of a revealed numbered cell if flag count matches.

        Returns False if this triggers a mine explosion.
        """
        if self.state[r][c] != CELL_REVEALED or self.counts[r][c] == 0:
            return True
        flagged = sum(
            1 for nr, nc in self.neighbors(r, c) if self.state[nr][nc] == CELL_FLAGGED
        )
        if flagged != self.counts[r][c]:
            return True
        ok = True
        for nr, nc in self.neighbors(r, c):
            if self.state[nr][nc] == CELL_HIDDEN:
                if not self.reveal(nr, nc):
                    ok = False
        return ok

    def reveal_all_mines(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.is_mine[r][c] and self.state[r][c] == CELL_HIDDEN:
                    self.state[r][c] = CELL_REVEALED

    def flag_all_mines(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.is_mine[r][c] and self.state[r][c] == CELL_HIDDEN:
                    self.state[r][c] = CELL_FLAGGED
                    self.flags_used += 1

    def is_won(self):
        return self.revealed_count == self.rows * self.cols - self.mines_total


class Game:
    PLAYING, WON, LOST = "playing", "won", "lost"

    def __init__(self, rows, cols, mines, label):
        self.board = Board(rows, cols, mines)
        self.label = label
        self.status = Game.PLAYING
        self.start_time = None
        self.end_time = None

    def elapsed(self):
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else time.time()
        return end - self.start_time

    def reveal(self, r, c):
        if self.status != Game.PLAYING:
            return
        if self.board.state[r][c] == CELL_FLAGGED:
            return
        if self.start_time is None:
            self.start_time = time.time()
        ok = self.board.reveal(r, c)
        self._after_move(ok)

    def chord(self, r, c):
        if self.status != Game.PLAYING:
            return
        if self.start_time is None:
            self.start_time = time.time()
        ok = self.board.chord(r, c)
        self._after_move(ok)

    def toggle_flag(self, r, c):
        if self.status != Game.PLAYING:
            return
        if self.board.state[r][c] == CELL_REVEALED:
            return
        if self.start_time is None:
            self.start_time = time.time()
        self.board.toggle_flag(r, c)

    def _after_move(self, ok):
        if not ok:
            self.status = Game.LOST
            self.end_time = time.time()
            self.board.reveal_all_mines()
        elif self.board.is_won():
            self.status = Game.WON
            self.end_time = time.time()
            self.board.flag_all_mines()


NUM_COLOR_PAIR = {
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6,
    7: 7,
    8: 8,
}


def init_colors():
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(1, curses.COLOR_BLUE, bg)
    curses.init_pair(2, curses.COLOR_GREEN, bg)
    curses.init_pair(3, curses.COLOR_RED, bg)
    curses.init_pair(4, curses.COLOR_MAGENTA, bg)
    curses.init_pair(5, curses.COLOR_YELLOW, bg)
    curses.init_pair(6, curses.COLOR_CYAN, bg)
    curses.init_pair(7, curses.COLOR_WHITE, bg)
    curses.init_pair(8, curses.COLOR_WHITE, bg)
    curses.init_pair(9, curses.COLOR_WHITE, bg)   # hidden cell
    curses.init_pair(10, curses.COLOR_RED, bg)    # flag
    curses.init_pair(11, curses.COLOR_WHITE, curses.COLOR_RED)  # exploded mine
    curses.init_pair(12, curses.COLOR_YELLOW, bg)  # header / titles
    curses.init_pair(13, curses.COLOR_GREEN, bg)   # win banner
    curses.init_pair(14, curses.COLOR_RED, bg)     # lose banner
    curses.init_pair(15, curses.COLOR_BLACK, curses.COLOR_WHITE)  # cursor highlight fallback


CELL_W = 2  # on-screen columns used per board cell


class UI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.scores = load_scores()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(150)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except curses.error:
            pass
        try:
            curses.mouseinterval(0)
        except curses.error:
            pass
        if curses.has_colors():
            init_colors()
        self.color = curses.has_colors()

    def attr(self, pair, extra=0):
        if self.color:
            return curses.color_pair(pair) | extra
        return extra

    # ---------- top-level flow ----------

    def run(self):
        while True:
            choice = self.menu_screen()
            if choice is None:
                return
            rows, cols, mines, label = choice
            result = self.play(rows, cols, mines, label)
            if result == "quit":
                return
            # result == "menu" -> loop back to menu

    # ---------- difficulty menu ----------

    def menu_screen(self):
        idx = 0
        custom = {"rows": 16, "cols": 30, "mines": 40}
        while True:
            self.stdscr.erase()
            h, w = self.stdscr.getmaxyx()
            title = "TERMINAL MINESWEEPER"
            self.safe_addstr(1, max(0, (w - len(title)) // 2), title,
                              self.attr(12, curses.A_BOLD))

            lines = []
            lines.append("Select difficulty (Up/Down + Enter, or click):")
            lines.append("")
            for i, (name, r, c, m) in enumerate(DIFFICULTIES):
                if name == "Custom":
                    desc = f"Custom      {custom['rows']}x{custom['cols']}, {custom['mines']} mines"
                else:
                    desc = f"{name:<12} {r}x{c}, {m} mines"
                    key = score_key(r, c, m)
                    best = self.scores.get(key)
                    if best is not None:
                        desc += f"   best: {fmt_time(best)}"
                lines.append(desc)
            lines.append("")
            lines.append("(Custom: use Left/Right to change rows/cols/mines, Tab to switch field)")
            lines.append("q: quit")

            start_y = 3
            self.menu_item_rows = {}
            for i, text in enumerate(lines):
                y = start_y + i
                if y >= h - 1:
                    break
                menu_idx = i - 2  # offset for header lines
                if 0 <= menu_idx < len(DIFFICULTIES):
                    self.menu_item_rows[y] = menu_idx
                    attr = self.attr(15) if menu_idx == idx else self.attr(0)
                    if menu_idx == idx:
                        attr |= curses.A_REVERSE
                    self.safe_addstr(y, 2, text, attr)
                else:
                    self.safe_addstr(y, 2, text)

            self.stdscr.refresh()
            ch = self.stdscr.getch()
            if ch == -1:
                continue
            if ch == curses.KEY_RESIZE:
                continue
            if ch in (curses.KEY_UP, ord('k')):
                idx = (idx - 1) % len(DIFFICULTIES)
            elif ch in (curses.KEY_DOWN, ord('j')):
                idx = (idx + 1) % len(DIFFICULTIES)
            elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT) and DIFFICULTIES[idx][0] == "Custom":
                step = 1 if ch == curses.KEY_RIGHT else -1
                custom["mines"] = max(1, min(custom["rows"] * custom["cols"] - 9,
                                              custom["mines"] + step))
            elif ch in (ord('q'), ord('Q')):
                return None
            elif ch in (curses.KEY_ENTER, 10, 13, ord(' ')):
                name, r, c, m = DIFFICULTIES[idx]
                if name == "Custom":
                    picked = self.custom_screen(custom)
                    if picked is None:
                        continue
                    r, c, m = picked
                    custom["rows"], custom["cols"], custom["mines"] = r, c, m
                return (r, c, m, name)
            elif ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    if my in self.menu_item_rows:
                        chosen = self.menu_item_rows[my]
                        name, r, c, m = DIFFICULTIES[chosen]
                        if name == "Custom":
                            picked = self.custom_screen(custom)
                            if picked is None:
                                continue
                            r, c, m = picked
                            custom["rows"], custom["cols"], custom["mines"] = r, c, m
                        return (r, c, m, name)

    def custom_screen(self, custom):
        fields = ["rows", "cols", "mines"]
        field_idx = 0
        vals = dict(custom)
        while True:
            self.stdscr.erase()
            h, w = self.stdscr.getmaxyx()
            self.safe_addstr(1, 2, "Custom game - Left/Right adjust, Tab switch, Enter confirm, Esc cancel",
                              self.attr(12, curses.A_BOLD))
            max_mines = max(1, vals["rows"] * vals["cols"] - 9)
            vals["mines"] = min(vals["mines"], max_mines)
            for i, f in enumerate(fields):
                y = 3 + i
                label = f"{f.capitalize():<8}: {vals[f]}"
                attr = curses.A_REVERSE if i == field_idx else 0
                self.safe_addstr(y, 4, label, attr)
            self.safe_addstr(3 + len(fields) + 1, 4, f"(max mines for this size: {max_mines})")
            self.stdscr.refresh()
            ch = self.stdscr.getch()
            if ch == -1 or ch == curses.KEY_RESIZE:
                continue
            if ch in (27,):  # Esc
                return None
            elif ch == 9:  # Tab
                field_idx = (field_idx + 1) % len(fields)
            elif ch in (curses.KEY_UP,):
                field_idx = (field_idx - 1) % len(fields)
            elif ch in (curses.KEY_DOWN,):
                field_idx = (field_idx + 1) % len(fields)
            elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                step = 1 if ch == curses.KEY_RIGHT else -1
                f = fields[field_idx]
                lo = 5 if f in ("rows", "cols") else 1
                hi = 60 if f in ("rows", "cols") else max_mines
                vals[f] = max(lo, min(hi, vals[f] + step))
            elif ch in (curses.KEY_ENTER, 10, 13):
                return (vals["rows"], vals["cols"], vals["mines"])

    # ---------- gameplay ----------

    def play(self, rows, cols, mines, label):
        game = Game(rows, cols, mines, label)
        scroll_y, scroll_x = 0, 0
        cur_r, cur_c = 0, 0

        while True:
            h, w = self.stdscr.getmaxyx()
            layout = self.compute_layout(h, w, rows, cols)
            if layout is None:
                self.draw_too_small(h, w, rows, cols)
                ch = self.stdscr.getch()
                if ch == curses.KEY_RESIZE:
                    continue
                if ch in (ord('q'), ord('Q')):
                    return "quit"
                if ch in (ord('m'), ord('M')):
                    return "menu"
                continue

            board_top, board_left, view_rows, view_cols = layout

            # keep cursor inside viewport
            if cur_r < scroll_y:
                scroll_y = cur_r
            if cur_r >= scroll_y + view_rows:
                scroll_y = cur_r - view_rows + 1
            if cur_c < scroll_x:
                scroll_x = cur_c
            if cur_c >= scroll_x + view_cols:
                scroll_x = cur_c - view_cols + 1
            scroll_y = max(0, min(scroll_y, max(0, rows - view_rows)))
            scroll_x = max(0, min(scroll_x, max(0, cols - view_cols)))

            self.draw_game(game, board_top, board_left, view_rows, view_cols,
                            scroll_y, scroll_x, cur_r, cur_c)
            self.stdscr.refresh()

            ch = self.stdscr.getch()
            if ch == -1:
                continue  # just a timer tick / redraw
            if ch == curses.KEY_RESIZE:
                continue

            if game.status != Game.PLAYING:
                if ch in (ord('r'), ord('R')):
                    game = Game(rows, cols, mines, label)
                    scroll_y = scroll_x = 0
                    cur_r = cur_c = 0
                    continue
                if ch in (ord('m'), ord('M')):
                    return "menu"
                if ch in (ord('q'), ord('Q')):
                    return "quit"
                if ch == curses.KEY_MOUSE:
                    try:
                        curses.getmouse()
                    except curses.error:
                        pass
                continue

            if ch in (ord('q'), ord('Q')):
                return "quit"
            elif ch in (ord('m'), ord('M')):
                return "menu"
            elif ch in (ord('r'), ord('R')):
                game = Game(rows, cols, mines, label)
                scroll_y = scroll_x = 0
                cur_r = cur_c = 0
            elif ch in (curses.KEY_UP, ord('k')):
                cur_r = max(0, cur_r - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                cur_r = min(rows - 1, cur_r + 1)
            elif ch in (curses.KEY_LEFT, ord('h')):
                cur_c = max(0, cur_c - 1)
            elif ch in (curses.KEY_RIGHT, ord('l')):
                cur_c = min(cols - 1, cur_c + 1)
            elif ch in (curses.KEY_ENTER, 10, 13, ord(' ')):
                game.reveal(cur_r, cur_c)
            elif ch in (ord('f'), ord('F')):
                game.toggle_flag(cur_r, cur_c)
            elif ch in (ord('c'), ord('C')):
                game.chord(cur_r, cur_c)
            elif ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    bstate = 0
                    mx = my = -1
                cell = self.screen_to_cell(mx, my, board_top, board_left,
                                            scroll_y, scroll_x, rows, cols)
                if bstate & BUTTON5_PRESSED:
                    scroll_y = min(max(0, rows - view_rows), scroll_y + 2)
                elif bstate & curses.BUTTON4_PRESSED:
                    scroll_y = max(0, scroll_y - 2)
                elif cell is not None:
                    r, c = cell
                    cur_r, cur_c = r, c
                    if bstate & curses.BUTTON1_DOUBLE_CLICKED:
                        game.chord(r, c)
                    elif bstate & getattr(curses, "BUTTON2_CLICKED", 0) or \
                            bstate & getattr(curses, "BUTTON2_PRESSED", 0):
                        game.chord(r, c)
                    elif bstate & (curses.BUTTON3_CLICKED | curses.BUTTON3_PRESSED):
                        game.toggle_flag(r, c)
                    elif bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                        if game.board.state[r][c] == CELL_REVEALED:
                            game.chord(r, c)
                        else:
                            game.reveal(r, c)

            if game.status == Game.WON:
                self.record_score(rows, cols, mines, game.elapsed())

    # ---------- layout & rendering ----------

    def compute_layout(self, h, w, rows, cols):
        header_lines = 3
        footer_lines = 2
        col_header_lines = 1
        row_label_w = len(str(rows - 1)) + 1

        avail_h = h - header_lines - footer_lines - col_header_lines
        avail_w = w - row_label_w

        if avail_h < 3 or avail_w < CELL_W * 3:
            return None

        view_rows = min(rows, avail_h)
        view_cols = min(cols, avail_w // CELL_W)
        if view_rows < 1 or view_cols < 1:
            return None

        board_top = header_lines + col_header_lines
        board_left = row_label_w
        return board_top, board_left, view_rows, view_cols

    def draw_too_small(self, h, w, rows, cols):
        self.stdscr.erase()
        msg1 = "Terminal window too small."
        msg2 = f"Need more space for a {rows}x{cols} board."
        msg3 = f"Current size: {w}x{h}. Resize the window, or press 'm' for menu, 'q' to quit."
        for i, msg in enumerate((msg1, msg2, msg3)):
            y = max(0, h // 2 - 1 + i)
            x = max(0, (w - len(msg)) // 2)
            self.safe_addstr(y, x, msg)
        self.stdscr.refresh()

    def screen_to_cell(self, mx, my, board_top, board_left, scroll_y, scroll_x, rows, cols):
        if my < board_top or mx < board_left:
            return None
        r = my - board_top + scroll_y
        c = (mx - board_left) // CELL_W + scroll_x
        if 0 <= r < rows and 0 <= c < cols:
            return r, c
        return None

    def cell_glyph(self, game, r, c):
        b = game.board
        s = b.state[r][c]
        if s == CELL_FLAGGED:
            return "F", self.attr(10, curses.A_BOLD)
        if s == CELL_HIDDEN:
            return "#", self.attr(9)
        # revealed
        if b.is_mine[r][c]:
            if game.board.exploded == (r, c):
                return "*", self.attr(11, curses.A_BOLD)
            return "*", self.attr(3, curses.A_BOLD)
        n = b.counts[r][c]
        if n == 0:
            return ".", self.attr(0)
        return str(n), self.attr(NUM_COLOR_PAIR.get(n, 0), curses.A_BOLD)

    def draw_game(self, game, board_top, board_left, view_rows, view_cols,
                  scroll_y, scroll_x, cur_r, cur_c):
        stdscr = self.stdscr
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        b = game.board

        title = f"MINESWEEPER - {game.label} ({b.rows}x{b.cols})"
        self.safe_addstr(0, 1, title, self.attr(12, curses.A_BOLD))

        mines_left = b.mines_total - b.flags_used
        timer_str = fmt_time(game.elapsed())
        best = self.scores.get(score_key(b.rows, b.cols, b.mines_total))
        best_str = fmt_time(best) if best is not None else "--:--"
        status_line = f"Mines: {mines_left:>4}   Time: {timer_str}   Best: {best_str}"
        self.safe_addstr(1, 1, status_line, self.attr(0))

        if game.status == Game.WON:
            self.safe_addstr(1, len(status_line) + 4, "YOU WIN!", self.attr(13, curses.A_BOLD))
        elif game.status == Game.LOST:
            self.safe_addstr(1, len(status_line) + 4, "BOOM! Game over.", self.attr(14, curses.A_BOLD))

        # column header
        row_label_w = board_left
        hdr_y = board_top - 1
        header = []
        for c in range(scroll_x, scroll_x + view_cols):
            header.append(f"{c % 100:>2}"[-CELL_W:])
        self.safe_addstr(hdr_y, row_label_w, "".join(header), self.attr(8))

        for i, r in enumerate(range(scroll_y, scroll_y + view_rows)):
            y = board_top + i
            label = f"{r:>{row_label_w - 1}} "
            self.safe_addstr(y, 0, label, self.attr(8))
            for j, c in enumerate(range(scroll_x, scroll_x + view_cols)):
                x = board_left + j * CELL_W
                glyph, attr = self.cell_glyph(game, r, c)
                if r == cur_r and c == cur_c:
                    attr = attr | curses.A_REVERSE
                self.safe_addstr(y, x, glyph + " ", attr)

        footer_y = board_top + view_rows + 1
        if view_rows < b.rows or view_cols < b.cols:
            hint = "Board larger than screen: scroll follows cursor / mouse wheel. "
        else:
            hint = ""
        controls = hint + "Arrows/hjkl move  Enter/Space reveal  f flag  c chord  r restart  m menu  q quit"
        self.safe_addstr(footer_y, 1, controls[: max(0, w - 2)], self.attr(0))
        if game.status != Game.PLAYING:
            self.safe_addstr(footer_y + 1 if footer_y + 1 < h else footer_y,
                              1, "Press 'r' to play again or 'm' for menu.", self.attr(0))

    def safe_addstr(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        if x < 0:
            text = text[-x:]
            x = 0
        maxlen = w - x
        if maxlen <= 0:
            return
        try:
            self.stdscr.addstr(y, x, text[:maxlen], attr)
        except curses.error:
            pass

    def record_score(self, rows, cols, mines, elapsed):
        key = score_key(rows, cols, mines)
        best = self.scores.get(key)
        if best is None or elapsed < best:
            self.scores[key] = elapsed
            save_scores(self.scores)


def main(stdscr):
    _enable_windows_console_mouse()
    ui = UI(stdscr)
    ui.run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    sys.exit(0)
