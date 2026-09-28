# Terminal Minesweeper

A fully-featured Minesweeper game for the terminal, built with Python's
built-in `curses` library — mouse-clickable, keyboard-playable, resizable,
and with persistent best-time tracking.

## Requirements

- Python 3.7+ (standard library only, no dependencies on macOS/Linux)
- A terminal that supports mouse reporting for click controls (most modern
  terminals do: xterm, iTerm2, gnome-terminal, tmux, Windows Terminal, etc.)
  Keyboard controls always work, even without mouse support.
- **Windows only**: Python's `curses` module isn't shipped on Windows. Install
  the drop-in replacement once with:

  ```powershell
  pip install windows-curses
  ```

  Then run the game normally from cmd, PowerShell, or Windows Terminal.

## Running

```bash
python3 minesweeper.py
```

or, if it's executable:

```bash
./minesweeper.py
```

## Features

- **Mouse controls**
  - Left click: reveal a cell (clicking a revealed number chords it)
  - Right click: place/remove a flag
  - Middle click or double-click: chord (reveal all neighbors of a
    satisfied number)
  - Mouse wheel: scroll the board when it's larger than your terminal
- **Keyboard controls**
  - Arrow keys / `h j k l`: move the cursor
  - `Enter` / `Space`: reveal the selected cell
  - `f`: toggle a flag on the selected cell
  - `c`: chord the selected cell
  - `r`: restart the current difficulty
  - `m`: return to the difficulty menu
  - `q`: quit
- **Difficulties**: Beginner (9x9, 10 mines), Intermediate (16x16, 40 mines),
  Expert (16x30, 99 mines), and a fully adjustable Custom size/mine count.
- **Safe first click**: mines are placed only after your first reveal, and
  never under it or its immediate neighbors.
- **Live timer** and **mines-remaining counter**.
- **Best times** are tracked per board configuration and saved to
  `~/.minesweeper_scores.json`, shown on the menu and in-game.
- **Fully resizable**: the board recenters/redraws on any terminal resize.
  If your terminal is too small for the current board it scrolls to follow
  your cursor or the mouse wheel; if it's too small even for that, you'll
  get a clear prompt to enlarge the window instead of a broken layout.

## Notes

- Colors follow classic Minesweeper number conventions (1=blue, 2=green,
  3=red, etc.) and degrade gracefully on terminals without color support.
- Score history lives outside the repo in your home directory, so it
  persists across game updates.
