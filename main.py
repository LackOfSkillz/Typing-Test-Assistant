import tkinter as tk
import customtkinter as ctk
from pynput import keyboard # Only for GlobalHotKeys
import threading
import json
import time
import random
import os
from PIL import ImageGrab, Image
import pytesseract
import pyautogui # The robust library for controlling the keyboard
import difflib # For intelligent text comparison

# --- DEFINITIVE FIX: Disable the PyAutoGUI Fail-Safe ---
pyautogui.FAILSAFE = False

# --- TESSERACT PATH ---
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- CONFIGURATION MANAGEMENT ---
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "wpm": 50, "variation": 10, "accuracy": 98.5,
    "activation_hotkey": "<ctrl>+<alt>+]", "gui_hotkey": "<ctrl>+<alt>+g"
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f: json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, IOError):
        with open(CONFIG_FILE, 'w') as f: json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)

class AppController:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.gui_instance = None
        
        self.STATE = "IDLE"
        self.monitoring_thread = None
        self.stop_monitoring_event = threading.Event()
        self.is_typing_event = threading.Event()
        self.MONITOR_INTERVAL = 1.5

    def start_hotkey_listener(self):
        hotkeys_map = {
            self.config['activation_hotkey']: lambda: self.root.after(0, self.on_activation_hotkey),
            self.config['gui_hotkey']: lambda: self.root.after(0, self.toggle_gui)
        }
        with keyboard.GlobalHotKeys(hotkeys_map) as h:
            print(f"Hotkey listener started. Press {self.config['activation_hotkey']} to start/stop monitoring, or {self.config['gui_hotkey']} for settings.")
            h.join()

    def on_activation_hotkey(self):
        print(f"--- Activation Hotkey Pressed. Current State: {self.STATE} ---")
        if self.STATE == "IDLE":
            if self.is_typing_event.is_set():
                print("Typing is in progress. Please wait.")
                return
            threading.Thread(target=self.run_initial_capture, daemon=True).start()
        elif self.STATE == "MONITORING":
            self.stop_monitoring()

    def run_initial_capture(self):
        print("Starting capture sequence...")
        self.root.after(0, self.select_area_and_process)

    def select_area_and_process(self):
        coords = self.select_screen_area()
        if not coords:
            print("Area selection cancelled."); return

        threading.Thread(target=self.process_initial_text, args=(coords,), daemon=True).start()

    def process_initial_text(self, coords):
        screen_width = self.root.winfo_screenwidth(); screen_height = self.root.winfo_screenheight()
        clamped_coords = (max(0, coords[0]), max(0, coords[1]), min(screen_width, coords[2]), min(screen_height, coords[3]))
        
        if clamped_coords[0] >= clamped_coords[2] or clamped_coords[1] >= clamped_coords[3]:
            print("Invalid area selected."); return
        
        print("Area selected. Performing initial OCR...")
        extracted_text = self._perform_ocr(clamped_coords)
        if not extracted_text: return

        print("Text captured. Typing will begin in 8 seconds...")
        self.show_notification_on_main_thread("Text Captured", "Typing starts in 8 seconds. Click in your target window NOW.")
        time.sleep(8)
        
        self.start_typing(extracted_text)
        
        self.start_monitoring_loop(clamped_coords, extracted_text)
        
    def start_monitoring_loop(self, coords, initial_text):
        if self.STATE == "MONITORING": return
        self.STATE = "MONITORING"
        print(f"Initial typing finished. Now entering LIVE MONITORING mode. State: {self.STATE}")
        self.stop_monitoring_event.clear()
        self.monitoring_thread = threading.Thread(target=self.monitoring_loop, args=(coords, initial_text), daemon=True)
        self.monitoring_thread.start()

    def stop_monitoring(self):
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            print("Stop signal received. Halting monitoring loop...")
            self.stop_monitoring_event.set()
        self.STATE = "IDLE"
        print("Monitoring stopped. Ready to start again.")
        self.show_notification_on_main_thread("Monitoring Stopped", "The application is now idle.")

    def _perform_ocr(self, coords):
        try:
            image = ImageGrab.grab(bbox=coords)
            grayscale_image = image.convert('L')
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(grayscale_image, config=custom_config)
            cleaned_text = text.replace('\n', ' ').replace('  ', ' ')
            if not cleaned_text.strip(): print("OCR returned empty text."); return None
            return cleaned_text
        except Exception as e:
            print(f"An OCR error occurred: {e}"); self.show_notification_on_main_thread("OCR Error", f"Could not perform OCR: {e}"); return None

    def monitoring_loop(self, coords, last_text):
        while not self.stop_monitoring_event.is_set():
            time.sleep(self.MONITOR_INTERVAL)
            if self.stop_monitoring_event.is_set(): break

            current_text = self._perform_ocr(coords)
            if current_text and current_text != last_text:
                print("Change detected!")
                new_portion = self.get_new_text(last_text, current_text)
                
                if new_portion.strip():
                    print(f"New text found, preparing to type:\n--- START ---\n{new_portion.strip()}\n--- END ---")
                    self.start_typing(" " + new_portion)
                last_text = current_text
        print("Monitoring loop has exited.")
        
    def get_new_text(self, old_text, new_text):
        if new_text.startswith(old_text):
            return new_text[len(old_text):]
        old_words = old_text.split(); new_words = new_text.split()
        s = difflib.SequenceMatcher(None, old_words, new_words)
        new_text_to_type = []
        for tag, i1, i2, j1, j2 in s.get_opcodes():
            if tag == 'replace' or tag == 'insert':
                new_text_to_type.extend(new_words[j1:j2])
        return " ".join(new_text_to_type) if new_text_to_type else ""

    def select_screen_area(self):
        selector = ScreenSelector(self.root); return selector.get_coords()
        
    def start_typing(self, text_to_type):
        if self.is_typing_event.is_set(): return
        self.is_typing_event.set()
        
        print("Starting typing loop...")
        current_config = load_config()
        try: wpm = float(current_config.get('wpm', 50))
        except: wpm = 50
        try: variation = float(current_config.get('variation', 10))
        except: variation = 10
        try: accuracy = float(current_config.get('accuracy', 98.5))
        except: accuracy = 98.5

        CALIBRATION_FACTOR = 34 / 50
        
        avg_chars_per_word = 5
        if wpm > 0: base_delay = 60.0 / (wpm * avg_chars_per_word)
        else: base_delay = 0.1
        
        words = text_to_type.split()
        for i, word in enumerate(words):
            for char in word:
                if random.uniform(0, 100) > accuracy:
                    pyautogui.write(random.choice('abcdefghijklmnopqrstuvwxyz'), interval=0)
                    time.sleep(random.uniform(0.15, 0.3))
                    pyautogui.press('backspace')
                    time.sleep(random.uniform(0.1, 0.2))
                
                pyautogui.write(char, interval=0)

                # --- NEW LOGIC FOR DOUBLE SPACE AFTER PERIOD ---
                if char == '.':
                    pyautogui.press('space')

                delay = random.uniform(base_delay * (1 - variation/100), base_delay * (1 + variation/100))
                calibrated_delay = delay * CALIBRATION_FACTOR
                time.sleep(max(0.01, calibrated_delay))
            
            # Add a single space after each word is complete
            if i < len(words) - 1:
                pyautogui.press('space')

        print("Typing of current block finished.")
        self.is_typing_event.clear()

    def toggle_gui(self):
        if self.gui_instance is None or not self.gui_instance.winfo_exists():
            self.gui_instance = TypingAutomatorGUI(self); self.gui_instance.protocol("WM_DELETE_WINDOW", self.on_gui_close)
        else:
            if self.gui_instance.state() == 'normal': self.gui_instance.withdraw()
            else: self.gui_instance.deiconify(); self.gui_instance.focus_force()

    def on_gui_close(self):
        if self.gui_instance:
            self.gui_instance.save_settings_to_config(); self.gui_instance.destroy(); self.gui_instance = None
            print("Settings saved.")

    def show_notification_on_main_thread(self, title, message):
        self.root.after(0, self.show_notification, title, message)

    def show_notification(self, title, message, duration=5000):
        notification = ctk.CTkToplevel(self.root); notification.title(title)
        screen_width = notification.winfo_screenwidth(); screen_height = notification.winfo_screenheight()
        notification.geometry(f"300x100+{screen_width - 320}+{screen_height - 150}")
        label = ctk.CTkLabel(notification, text=message, wraplength=280); label.pack(pady=20, padx=10, expand=True, fill='both')
        notification.attributes("-topmost", True); notification.after(duration, notification.destroy)

class ScreenSelector(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.withdraw()
        self.attributes('-fullscreen', True); self.attributes('-alpha', 0.3); self.configure(cursor="crosshair")
        self.canvas = ctk.CTkCanvas(self, bg='black', highlightthickness=0); self.canvas.pack(fill="both", expand=True)
        self.start_x = self.start_y = self.rect = self.coords = None
        self.deiconify(); self.lift(); self.focus_force(); self.grab_set()
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
    def on_button_press(self, event):
        self.start_x = self.canvas.canvasx(event.x); self.start_y = self.canvas.canvasy(event.y)
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=2)
    def on_mouse_drag(self, event):
        cur_x, cur_y = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)
    def on_button_release(self, event):
        self.grab_release()
        self.coords = (min(self.start_x, event.x), min(self.start_y, event.y), max(self.start_x, event.x), max(self.start_y, event.y))
        self.destroy()
    def get_coords(self):
        self.master.wait_window(self); return self.coords

class TypingAutomatorGUI(ctk.CTkToplevel):
    def __init__(self, controller):
        super().__init__(controller.root)
        self.controller = controller; self.config = load_config()
        self.title("Typing Automator Settings"); self.geometry("400x320"); self.resizable(False, False)
        self.attributes("-topmost", True); self.grid_columnconfigure(1, weight=1)
        labels = ["Average Words Per Minute:", "Speed Variation (%):", "Accuracy (%):"]
        entries = []
        for i, text in enumerate(labels):
            label = ctk.CTkLabel(self, text=text); label.grid(row=i, column=0, padx=20, pady=10, sticky="w")
            entry = ctk.CTkEntry(self); entry.grid(row=i, column=1, padx=20, pady=10, sticky="ew")
            entries.append(entry)
        self.wpm_entry, self.variation_entry, self.accuracy_entry = entries
        self.wpm_entry.insert(0, self.config.get('wpm', '')); self.variation_entry.insert(0, self.config.get('variation', '')); self.accuracy_entry.insert(0, self.config.get('accuracy', ''))
        self.info_label = ctk.CTkLabel(self, text="Restart app for hotkey changes to apply.", text_color="gray"); self.info_label.grid(row=3, column=0, columnspan=2, padx=20, pady=(15, 0))
        self.activation_hotkey_label = ctk.CTkLabel(self, text="Activation Hotkey:"); self.activation_hotkey_label.grid(row=4, column=0, padx=20, pady=10, sticky="w")
        self.activation_hotkey_entry = ctk.CTkEntry(self); self.activation_hotkey_entry.grid(row=4, column=1, padx=20, pady=10, sticky="ew")
        self.activation_hotkey_entry.insert(0, self.config.get('activation_hotkey', ''))
        self.gui_hotkey_label = ctk.CTkLabel(self, text="GUI Hotkey:"); self.gui_hotkey_label.grid(row=5, column=0, padx=20, pady=10, sticky="w")
        self.gui_hotkey_entry = ctk.CTkEntry(self); self.gui_hotkey_entry.grid(row=5, column=1, padx=20, pady=10, sticky="ew")
        self.gui_hotkey_entry.insert(0, self.config.get('gui_hotkey', ''))
    def save_settings_to_config(self):
        new_config = {"wpm": self.wpm_entry.get(), "variation": self.variation_entry.get(), "accuracy": self.accuracy_entry.get(),
            "activation_hotkey": self.activation_hotkey_entry.get(), "gui_hotkey": self.gui_hotkey_entry.get()}
        save_config(new_config);

if __name__ == "__main__":
    try:
        root = ctk.CTk()
        root.withdraw()
        app_controller = AppController(root)
        hotkey_thread = threading.Thread(target=app_controller.start_hotkey_listener, daemon=True)
        hotkey_thread.start()
        root.mainloop()
    except KeyboardInterrupt:
        print("\nApplication closed by user. Exiting gracefully.")
    except Exception as e:
        print(f"\nAn unexpected critical error occurred: {e}")