import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import json
import threading
import time
import csv
from datetime import datetime

# --- Alarm Threshold Configuration ---
LIMITS = {
    "temp_1_c": {"min": 5.0, "max": 35.0, "unit": "°C", "label": "SHT35 Temp 1"},
    "temp_2_c": {"min": 5.0, "max": 35.0, "unit": "°C", "label": "SHT35 Temp 2"},
    "hum_1_pct": {"min": 20.0, "max": 85.0, "unit": "%", "label": "SHT35 Humidity 1"},
    "hum_2_pct": {"min": 20.0, "max": 85.0, "unit": "%", "label": "SHT35 Humidity 2"},
    "water_1_pct": {"min": 15.0, "max": 95.0, "unit": "%", "label": "Water Level 1"},
    "water_2_pct": {"min": 15.0, "max": 95.0, "unit": "%", "label": "Water Level 2"},
    "dist_1_cm": {"min": 10.0, "max": 200.0, "unit": "cm", "label": "Ultrasonic Dist 1"},
    "dist_2_cm": {"min": 10.0, "max": 200.0, "unit": "cm", "label": "Ultrasonic Dist 2"},
    "weight_1_kg": {"min": 0.0, "max": 90.0, "unit": "kg", "label": "Load Cell 1"},
    "weight_2_kg": {"min": 0.0, "max": 90.0, "unit": "kg", "label": "Load Cell 2"},
    "soil_moist_pct": {"min": 15.0, "max": 80.0, "unit": "%", "label": "Soil Moisture"},
    "soil_temp_c": {"min": 5.0, "max": 35.0, "unit": "°C", "label": "Soil Temp"},
    "soil_ec_us": {"min": 0.0, "max": 2000.0, "unit": "µS/cm", "label": "Soil EC"},
    "soil_ph": {"min": 5.5, "max": 7.8, "unit": "pH", "label": "Soil pH"},
}

LOG_FILE = "sensor_data_log.csv"


class SensorDashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Multi-Sensor Control & Monitoring Dashboard (Windows 11)")
        self.root.geometry("1050x720")
        self.root.configure(bg="#1e1e2e")

        self.serial_conn = None
        self.is_running = False
        self.cards = {}
        self.value_labels = {}

        self.setup_ui()
        self.init_csv()

    def init_csv(self):
        try:
            with open(LOG_FILE, mode="x", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp"] + list(LIMITS.keys()))
        except FileExistsError:
            pass

    def setup_ui(self):
        # Top Control Bar
        top_frame = tk.Frame(self.root, bg="#181825", pady=10, padx=15)
        top_frame.pack(fill="x")

        tk.Label(
            top_frame, text="COM Port:", fg="#cdd6f4", bg="#181825", font=("Segoe UI", 10, "bold")
        ).pack(side="left", padx=(0, 5))

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top_frame, textvariable=self.port_var, width=15, state="readonly")
        self.port_combo.pack(side="left", padx=5)
        self.refresh_ports()

        tk.Button(
            top_frame, text="Refresh", command=self.refresh_ports, bg="#313244", fg="#cdd6f4", relief="flat", padx=10
        ).pack(side="left", padx=5)

        self.connect_btn = tk.Button(
            top_frame, text="Connect", command=self.toggle_connection, bg="#a6e3a1", fg="#11111b",
            font=("Segoe UI", 10, "bold"), relief="flat", padx=15
        )
        self.connect_btn.pack(side="left", padx=10)

        self.status_label = tk.Label(
            top_frame, text="Status: Disconnected", fg="#f38ba8", bg="#181825", font=("Segoe UI", 10, "bold")
        )
        self.status_label.pack(side="right")

        # Tare buttons frame
        tare_frame = tk.Frame(self.root, bg="#181825", pady=5, padx=15)
        tare_frame.pack(fill="x")

        tk.Label(tare_frame, text="Scale Tare:", fg="#cdd6f4", bg="#181825", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))

        self.tare1_btn = tk.Button(
            tare_frame, text="Tare Scale 1", command=lambda: self.send_tare("TARE1"),
            bg="#89b4fa", fg="#11111b", font=("Segoe UI", 10, "bold"), relief="flat", padx=15, state="disabled"
        )
        self.tare1_btn.pack(side="left", padx=5)

        self.tare2_btn = tk.Button(
            tare_frame, text="Tare Scale 2", command=lambda: self.send_tare("TARE2"),
            bg="#89b4fa", fg="#11111b", font=("Segoe UI", 10, "bold"), relief="flat", padx=15, state="disabled"
        )
        self.tare2_btn.pack(side="left", padx=5)

        # Alarm Banner
        self.alarm_banner = tk.Label(
            self.root, text="SYSTEM NORMAL - ALL PARAMETERS WITHIN LIMITS",
            bg="#2e7d32", fg="white", font=("Segoe UI", 11, "bold"), pady=8
        )
        self.alarm_banner.pack(fill="x", padx=15, pady=(10, 5))

        # Sensor Grid Container
        grid_frame = tk.Frame(self.root, bg="#1e1e2e", padx=15, pady=10)
        grid_frame.pack(fill="both", expand=True)

        cols = 4
        for idx, (key, info) in enumerate(LIMITS.items()):
            row = idx // cols
            col = idx % cols

            card = tk.Frame(grid_frame, bg="#313244", bd=2, relief="ridge", padx=12, pady=12)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            grid_frame.grid_columnconfigure(col, weight=1)
            grid_frame.grid_rowconfigure(row, weight=1)

            title_lbl = tk.Label(
                card, text=info["label"], fg="#bac2de", bg="#313244", font=("Segoe UI", 10, "bold")
            )
            title_lbl.pack(anchor="w")

            val_lbl = tk.Label(
                card, text=f"-- {info['unit']}", fg="#ffffff", bg="#313244", font=("Segoe UI", 18, "bold")
            )
            val_lbl.pack(pady=(6, 4))

            limit_lbl = tk.Label(
                card, text=f"Range: {info['min']} - {info['max']} {info['unit']}",
                fg="#a6adc8", bg="#313244", font=("Segoe UI", 8)
            )
            limit_lbl.pack(anchor="w")

            self.cards[key] = (card, title_lbl, val_lbl, limit_lbl)
            self.value_labels[key] = val_lbl

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_combo.current(0)

    def toggle_connection(self):
        if not self.is_running:
            port = self.port_var.get()
            if not port:
                messagebox.showwarning("Port Error", "Please select a valid COM port.")
                return
            try:
                self.serial_conn = serial.Serial(port, 115200, timeout=1)
                self.is_running = True
                self.connect_btn.config(text="Disconnect", bg="#f38ba8")
                self.status_label.config(text=f"Status: Connected ({port})", fg="#a6e3a1")
                self.tare1_btn.config(state="normal")
                self.tare2_btn.config(state="normal")
                threading.Thread(target=self.read_serial_loop, daemon=True).start()
            except Exception as e:
                messagebox.showerror("Connection Failed", str(e))
        else:
            self.is_running = False
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            self.connect_btn.config(text="Connect", bg="#a6e3a1")
            self.status_label.config(text="Status: Disconnected", fg="#f38ba8")
            self.tare1_btn.config(state="disabled")
            self.tare2_btn.config(state="disabled")

    def send_tare(self, command):
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write((command + "\n").encode())
            except Exception as e:
                messagebox.showerror("Tare Error", str(e))

    def read_serial_loop(self):
        while self.is_running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("{") and line.endswith("}"):
                        data = json.loads(line)
                        # Ignore status messages from tare
                        if "status" not in data:
                            self.root.after(0, self.update_dashboard, data)
                            self.log_to_csv(data)
            except Exception:
                pass
            time.sleep(0.05)

    def log_to_csv(self, data):
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        for key in LIMITS.keys():
            row.append(data.get(key, ""))
        with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def update_dashboard(self, data):
        active_alarms = []

        for key, info in LIMITS.items():
            if key in data and data[key] is not None:
                val = float(data[key])
                card, title_lbl, val_lbl, limit_lbl = self.cards[key]
                val_lbl.config(text=f"{val} {info['unit']}")

                # Check alarm thresholds
                if val < info["min"] or val > info["max"] or val < 0:
                    bg_color = "#b71c1c"  # Red alarm background
                    active_alarms.append(info["label"])
                else:
                    bg_color = "#313244"  # Normal dark card background

                card.config(bg=bg_color)
                title_lbl.config(bg=bg_color)
                val_lbl.config(bg=bg_color)
                limit_lbl.config(bg=bg_color)

        if active_alarms:
            self.alarm_banner.config(
                text=f"ALARM TRIGGERED: {', '.join(active_alarms)}",
                bg="#c62828"
            )
        else:
            self.alarm_banner.config(
                text="SYSTEM NORMAL - ALL PARAMETERS WITHIN LIMITS",
                bg="#2e7d32"
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = SensorDashboardApp(root)
    root.mainloop()
