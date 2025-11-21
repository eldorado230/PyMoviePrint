import os
import threading
import time
import pyautogui
import movieprint_gui
import customtkinter as ctk

def run_gui():
    app = movieprint_gui.MoviePrintApp()
    # Use a timer to close the app after a short delay to capture the screenshot
    app.after(5000, app.quit)
    app.mainloop()

if __name__ == "__main__":
    # Ensure the temp directory for verification exists
    os.makedirs("/home/jules/verification", exist_ok=True)

    # Start GUI in a separate thread so we can wait for it
    gui_thread = threading.Thread(target=run_gui)
    gui_thread.start()

    # Wait a bit for the GUI to render
    time.sleep(3)

    # Take a screenshot
    screenshot_path = "/home/jules/verification/gui_screenshot.png"
    try:
        pyautogui.screenshot(screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
    except Exception as e:
        print(f"Failed to take screenshot: {e}")

    # Wait for thread to finish (which happens after app.quit called by .after)
    gui_thread.join()
