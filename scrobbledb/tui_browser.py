# Finalized Textual TUI Browser

This is the finalized Textual TUI browser for browsing and filtering scrobbles.

## Features
- Browse through scrobbles seamlessly.
- Filter by various criteria.
- Friendly user interface using Textual framework.

## Usage
To use the TUI browser, run the following command:

```bash
python tui_browser.py
```

## Installation
Make sure you have the Textual framework installed:

```bash
pip install textual
```

## Example

```python
from textual.app import App

class ScrobbleApp(App):
    # Your app implementation

if __name__ == '__main__':
    ScrobbleApp.run()  
```