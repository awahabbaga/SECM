from collections import deque
import json
import os
import sys
import time
import csv

import pandas as pd
import kbio.kbio_types as KBIO
from kbio.c_utils import c_is_64b
from kbio.kbio_api import KBIO_api
import serial
import threading
import numpy as np
import pyqtgraph as pg
import serial.tools.list_ports
from kbio.utils import exception_brief
from approach_curve import perf_ca, send_command, read_response
from seccm_cv import perf_cv
from electro_tech import perf_tech_ca, perf_tech_cp
from elcetro_peis import perf_peis
from electro_sicm import perf_sicm
from electro_secm import perf_secm
from line_scan import perf_line_scan
from electro_abs_secm import perf_abs_secm
from electro_seccm import perf_seccm
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QButtonGroup, QComboBox, QLineEdit,QDockWidget,
    QGroupBox, QGridLayout, QMessageBox, QFileDialog, QCheckBox,
    QDialog, QDialogButtonBox, QFormLayout, QSizePolicy, QInputDialog,QScrollArea, QListWidget, QListWidgetItem,
    QStyle, QTextEdit, QSpacerItem
)
import serial
import threading
import numpy as np
from PyQt5.QtCore import Qt, QUrl, QThread, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QDesktopServices, QIcon, QColor, QTextFormat
import serial.tools.list_ports  # Import for serial port listing

# Resource path for PyInstaller compatibility
def resource_path(relative_path):
    """Retourne le chemin absolu vers une ressource, compatible PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

#write_lock = threading.Lock()
#read_lock = threading.Lock()

# Optionally set options :
#pg.setConfigOption('background', 'black')
#pg.setConfigOption('foreground', 'lightgray')

# -------------------------------
# Macro execution Thread
# -------------------------------

class MacroExecutorThread(QThread):
    highlight_line_signal = pyqtSignal(int)
    
    def __init__(self, macro_content, parent=None):
        super().__init__(parent)
        self.macro_content = macro_content
        self._paused = False  # Pause flag
        
    def run(self):
        try:
            from macro_inter import MacroInterpreter
            interpreter = MacroInterpreter()
            lines = self.macro_content.splitlines()
            interpreter.parse(lines)
            # Execute macro and use self.emit_highlight as callback.
            interpreter.execute(self.emit_highlight)
        except Exception as e:
            print("Error during macro execution:", e)
    
    def emit_highlight(self, line_number):
        # Check if a stop has been requested.
        if self.isInterruptionRequested():
            return
        self.highlight_line_signal.emit(line_number)
        # While paused, loop and sleep to prevent blocking the GUI.
        while self._paused:
            if self.isInterruptionRequested():
                return
            self.msleep(100)  # sleep 100 ms

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False


# -------------------------------
# Custom Widget for MPS/Options File Items
# -------------------------------
class FileItemWidget(QWidget):
    def __init__(self, file_name, remove_callback, parent=None):
        super().__init__(parent)
        self.file_name = file_name
        self.remove_callback = remove_callback

        layout = QHBoxLayout()
        layout.setContentsMargins(8, 0, 8, 0)
        self.label = QLabel(file_name)
        layout.addWidget(self.label)

        # Small "x" button for removal
        self.remove_btn = QPushButton('x')
        self.remove_btn.setToolTip('Remove file')
        self.remove_btn.setFixedSize(24, 24)
        self.remove_btn.setStyleSheet("background-color: red; color: black;")
        self.remove_btn.clicked.connect(self.remove_item)
        layout.addWidget(self.remove_btn)
        self.setLayout(layout)

    def remove_item(self):
        if self.remove_callback:
            self.remove_callback(self)

class MotorPositionThread(QThread):
    # Signal of x,y,z position
    position_values_signal = pyqtSignal(float,float,float,str)
    finished_signal = pyqtSignal()
    
    def __init__(self, electro, update_positions_name):
        super().__init__()
        self.electro = electro
        self.update_positions_name = update_positions_name
        self._is_running = True
    
    def run(self):
        print("ExperimentThread started. run ....")
        # Execute the technique function, passing necessary arguments
        self.update_positions_name(self.electro, self)
        print("ExperimentThread finished. run ...")

    def stop(self):
        self._is_running = False

class ExperimentThread(QThread):
    data_signal = pyqtSignal(float, float, float,int,str)
    seccm_cp_data_signal = pyqtSignal(float, float, float,int,str)
    seccm_ca_data_signal = pyqtSignal(float, float, float,int,str)
    secm_abs_cv_data_signal = pyqtSignal(float, float, float,int,str)
    seccm_approach_data_signal = pyqtSignal(float, float, float,int,str)
    seccm_cv_data_signal = pyqtSignal(float, float, float,int,str)
    seccm_retract_data_signal = pyqtSignal(float, float, float,int,str)
    seccm_record_position_signal = pyqtSignal(bool, str)
    data_signal_peis_1 = pyqtSignal(float, float, float, float, float, float, float, float, float, float, float,float,float, str)
    data_signal_peis_0 = pyqtSignal(float, float, float,str)
    current_values_signal = pyqtSignal(int,float, float,str)
    finished_signal = pyqtSignal()

    def __init__(self, electro, technique_function):
        super().__init__()
        self.electro = electro
        self.technique_function = technique_function
        self._is_running = True

    def run(self):
        print("ExperimentThread started. run ....")
        # Execute the technique function, passing necessary arguments
        self.technique_function(self.electro, self)
        print("ExperimentThread finished. run ...")

    def stop(self):
        self._is_running = False


class ElectroChemistryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Electro-Chemistry Measurements Software")
        self.setGeometry(100, 100, 1200, 800)

        #self.setStyleSheet("background-color: ;")

        self.write_lock = threading.Lock()
        self.read_lock = threading.Lock()

        self.rdp = 1
        self.channel_selected = 1

        # Initialize controller settings with default values
        self.controller_settings = {
            'unit': 'mm',
            'pitch': '1.0',
            'motor_pos_unit': 'um',
            'potentiostat_channel_count': '2',
        }

        # Initialze controller reboot settings with default values
        self.reboot_controller_settings = {
            'goback_x': '23395.9603',
            'goback_y': '47907.6186',
            'goback_z': '1000',
        }

        # Initialize serial port settings with default values
        self.serial_settings = {
            'port': 'COM23',
            'baud_rate': '115200',
            'data_bits': '8',
            'parity': 'None',
            'stop_bits': '1'
        }

        # Initialize techniques options with default values
        self.approach_options = {
            'vs_init': 'False',
            'approach_speed': '0.0001',
            'voltage_applied': '0.5',
            'estimated_approach_time': '5000',
            'spike_threshold': '2e-12'
        }
        self.turn_to_ocv = 'Yes' # Default is False which is that it turn to ocv. Yes= False

        self.line_options = {
            'x_length': '0',
            'x_speed': '1',
            'y_length': '0',
            'y_speed': '1',
            'scan_speed': '0.1', # mm/s
            'voltage_applied': '0.5', # Volt
            'estimated_line_time': '10000',
        }

        self.cv_options = {
            'Ei': '0.0',
            'E1': '0.0',
            'E2': '1.0',
            'Ef': '0.0',
            'Scan rate': '0.05',
            'Scan number': 2,
            'Record_every_dE': '0.0',
            'Average_over_dE': 'True',
            'N_Cycles': '0',
        }

        self.ca_options = {
            'vs_init': 'False',
            'voltage_applied': '0.5',
            'duration': '10.0',
            'record_dT': '0.1',
            'record_dI': '0.0',
            'N_Cycles': '0',
        }

        self.cp_options = {
            'vs_init': 'False',
            'current_applied': '0.5',
            'duration': '10.0',
            'record_dT': '0.1',
            'record_dE': '0.0',
            'N_Cycles': '0',
        }

        self.seccm_options = {
            'points_number': '3x3',
            'tech_measure': '',
            'x_width':'1',
            'y_length':'1',
            'retract_h': '0.015',
            'retract_s': '0.001',
        }
        self.write_seccm_position = False

        self.peis_options = {
            'vs_init':'False',
            'init_voltage_step':'0.1',
            'duration_step':'30.0',
            'record_dt':'0.1',
            'record_dI':'5e-6',
            'final_freq':'100.0E3',
            'initial_freq':'10.0E3',
            'sweep':'True',
            'amplitude_voltage':'0.1',
            'freq_number':'1',
            'avg_n':'1',
            'correction':'False',
            'wait_steady':'1.0',
        }

        self.sicm_options = {
            'z_speed': '0.001',
            'voltage': '0.02',
            'aproximate_time': '5000',
            'stop_point': '0.7'
        }

        self.secm_options = {
            'z_speed': '0.001',
            'voltage': '0.02',
            'aproximate_time': '5000',
            'stop_point': '0.9',
            'skip': '300',
        }
        self.abs_secm_options = {
            'voltage': '0.02',
            'aproximate_time': '5000',
            'distance': '0.155',
            'z_speed': '0.001',
            'nb_rounds':  '5',
            'current_pos': '0,0,0'
        }


        # Initialize data for plotting (placeholder data)
        # CA output data
        self.ca_Iwe = []
        self.ca_Ewe = []
        self.ca_time = []
        self.ca_cycle = []
        self.ca_local_time = []

        # tech CA output data
        self.tech_ca_Iwe = []
        self.tech_ca_Ewe = []
        self.tech_ca_time = []
        self.tech_ca_cycle = []
        self.tech_ca_local_time = []

        # tech CP output data
        self.tech_cp_Iwe = []
        self.tech_cp_Ewe = []
        self.tech_cp_time = []
        self.tech_cp_cycle = []
        self.tech_cp_local_time = []

        # SECCM Cv output data
        self.cv_Iwe = []
        self.cv_Ewe = []
        self.cv_time = []
        self.cv_cycle = []
        self.cv_local_time = []


        # PEIS output data
        self.peis_Iwe_0 = []
        self.peis_Ewe_0 = []
        self.peis_time_0 = []
        self.peis_f = []
        self.peis_abs_Iwe_1 = []
        self.peis_abs_Ewe_1 = []
        self.peis_phase_Zwe = []
        self.peis_phase_Zce = []
        self.peis_Iwe_1 = []
        self.peis_Ewe_1 = []
        self.peis_time_1 = []
        self.peis_abs_Zwe_1 = []
        self.peis_Zwe_real_1 = []
        self.peis_Zwe_imag_1 = []
        self.peis_phase_Zwe_deg_1 = []
        self.peis_log_f_1 = []
        self.peis_local_time = []


        # SICM output data
        self.sicm_Iwe = []
        self.sicm_Ewe = []
        self.sicm_time = []
        self.sicm_cycle = []
        self.sicm_local_time = []

        # SICM output data
        self.secm_Iwe = []
        self.secm_Ewe = []
        self.secm_time = []
        self.secm_cycle = []
        self.secm_local_time = []

        # Abs SICM output data
        self.abs_secm_Iwe = []
        self.abs_secm_Ewe = []
        self.abs_secm_time = []
        self.abs_secm_cycle = []
        self.abs_secm_local_time = []

        self.abs_secm_cv_Iwe = []
        self.abs_secm_cv_Ewe = []
        self.abs_secm_cv_time = []
        self.abs_secm_cv_cycle = []
        self.abs_secm_cv_local_time = []

        
        
        self.data = np.random.rand(10, 10)
        self.data_x = np.linspace(0, 10, 100)  # For line plot
        self.data_y = np.sin(self.data_x)

        # Graphic display data 
        self.data_time = []
        self.data_Ewe = []
        self.data_Iwe = []
        self.data_abs_Ewe = []
        self.data_abs_Iwe = []
        self.data_f = []
        self.data_phase_Zwe = []
        self.data_phase_Zce = [] 
        self.data_abs_Zwe = []
        self.data_Zwe_real = []
        self.data_Zwe_imag = []
        self.data_phase_Zwe_deg = []
        self.data_log_f = []

        # Data from file
        self.file_data_time = []
        self.file_data_Ewe = []
        self.file_data_Iwe = []
        
        # Graphic display variable
        self.available_axis_variables = {
            'Time (s)': 'time',
            'Ewe (V)': 'Ewe',
            'Iwe (A)': 'Iwe',
            'Phase Zwe': 'phase_Zwe',
            'Phase Zce': 'phase_Zce',
            'f (Hz)': 'f',
            '|Ewe| (V)': 'abs_Ewe',
            '|Iwe| (A)': 'abs_Iwe',
            'Re(Zwe)': 'Zwe_real',
            'Im(Zwe)': 'Zwe_imag',
            '|Zwe|': 'abs_Zwe',
            'Phase deg(Zwe)': 'phase_Zwe_deg',
            'log(f)': 'log_f',
        }
        # Data from file
        self.graphic_file_headers = []
        self.graphic_file_data = {}

        # Create a fixed-length buffer to store live data points.
        self.plot_buffer = {
            'time': deque(maxlen=10000000),
            'Iwe': deque(maxlen=10000000),
            'Ewe': deque(maxlen=10000000),
            'phase_Zwe': deque(maxlen=10000000),
            'phase_Zce': deque(maxlen=10000000),
            'f': deque(maxlen=10000000),
            'abs_Ewe': deque(maxlen=10000000),
            'abs_Iwe': deque(maxlen=10000000),
            'Zwe_real': deque(maxlen=10000000),
            'Zwe_imag': deque(maxlen=10000000),
            'abs_Zwe': deque(maxlen=10000000),
            'phase_Zwe_deg': deque(maxlen=10000000),
            'log_f': deque(maxlen=10000000),
        }

        # List of files produced names 
        self.files_produced = [
            """'electro_ca.csv', 'electro_cp.csv'""", 'electro_peis.csv', 'electro_peis_p2.csv', 
            'electro_abs_secm_out.csv', 'seccm_approach_file.csv', 'seccm_retract_file.csv', 
            'seccm_peis_p1.csv', 'seccm_peis_p2.csv', 'seccm_cv_file.csv', 'seccm_cp_file.csv',
            'seccm_ca_file.csv', 'electro_abs_secm_pos.csv', 'electro_secm_pos.csv', 'electro_secm_out.csv',
            ]

        # Current values
        self.current_i_value = 0
        self.current_ewe_value = 0
        self.channel_state_value = 0


        # Potentiostat settings
        self.potentiostat_connected = False
        self.channel_list_1 = ['1', '2']
        self.channel_list_2 = ['1', '2', '3', '4','5','6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16']
        self.channel_number = 2
        self.potentiostat_verbosity = 1
        self.potentiostat_address = "USB0"
        self.potentiostat_binary_path = "C:/EC-Lab Development Package_v/lib"
        self.potentiostat_force_load_firmware = True

        # Initialize UI
        self.stop_all = False
        self.init_ui()
        

    def init_ui(self):
        print("init ui started in thread:", QThread.currentThread())
        # Create Menus
        self.create_menus()

        # Initialize toolbar
        self.createToolbar()

        # Central Widget and Layouts
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QHBoxLayout()
        central_widget.setLayout(self.main_layout)

        # Left and Right Layouts
        self.left_layout = QVBoxLayout()
        self.right_layout = QVBoxLayout()
        self.default_stretch = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
        

        # Left Side Widgets
        self.left_layout.addWidget(self.create_input_box())
        self.left_layout.addWidget(self.create_joystick_box())
        self.left_layout.addWidget(self.create_macro_box())
        self.left_layout.addWidget(self.create_filter_box())
        self.left_layout.addWidget(self.create_stop_button())
        self.left_layout.addStretch()

        # Right Side Widgets
        self.right_layout.addWidget(self.create_motor_position_box())
        #self.update_motor_positions()
        self.right_layout.addWidget(self.create_output_box())
        self.right_layout.addWidget(self.create_technique_box())
        self.right_layout.addItem(self.default_stretch)
        
        # Add Left and Right Layouts to Main Layout
        self.main_layout.addLayout(self.left_layout, 2)
        self.main_layout.addLayout(self.right_layout, 3)

        # Create Dock Widgets
        #self.create_histogram_dock()
        self.create_graphic_display_dock()

    def createToolbar(self):
        self.toolbar = self.addToolBar("Main Toolbar")
        self.toolbar.setMovable(True)  # Make toolbar fixed

        # Connect/Disconnect Controller Action
        self.controller_connect_action = QAction(
            QIcon(resource_path('icons/connect_controller.png')), 'Connect controller device', self
        )
        self.controller_connect_action.setStatusTip('Connect to the controller device')
        self.controller_connect_action.setCheckable(True)
        self.controller_connect_action.triggered.connect(self.toggleControllerConnection)
        #controller_connect_action.triggered.connect(self.connectDevice)
        self.toolbar.addAction(self.controller_connect_action)

        self.toolbar.addSeparator() 
        self.toolbar.addSeparator() 
        # Connect/Disconnect Potentiostat Action
        self.potentiostat_connect_action = QAction(
            QIcon(resource_path('icons/plug-connect.png')), 'Connect to the potentiostat device', self
        )
        self.potentiostat_connect_action.setStatusTip('Connect to the potentiostat device')
        self.potentiostat_connect_action.setCheckable(True)
        self.potentiostat_connect_action.triggered.connect(self.togglePotentiostatConnection)
        self.toolbar.addAction(self.potentiostat_connect_action)

        self.toolbar.addSeparator()
        self.toolbar.addSeparator()

        # Channel Selection ComboBox
        channel_label = QAction('Channel:', self)
        self.toolbar.addAction(channel_label)

        self.channel_combo = QComboBox()
        self.channel_combo.addItems(self.channel_list_2)
        self.channel_combo.currentIndexChanged.connect(self.selectChannel)
        self.toolbar.addWidget(self.channel_combo)

    
    def toggleControllerConnection(self, checked):
        if checked:
            # Ouvre la boîte de dialogue de configuration série avant de se connecter
            dialog = QDialog(self)
            self.serial_setup()
            # Si l'utilisateur a fermé la boîte sans valider, on annule la connexion
            # (serial_setup ferme le dialog si Ok, sinon rien ne change)
            # On vérifie que le port est bien sélectionné
            if not self.serial_settings.get('port'):
                self.controller_connect_action.setChecked(False)
                return
            self.connectControllerDevice()
        else:
            self.disconnectControllerDevice()

    def togglePotentiostatConnection(self, checked):
        if checked:
            self.connectPotentiostatDevice()
        else:
            self.disconnectPotentiostatDevice()
    
    def connectControllerDevice(self):
         # Implement your controller connection logic here
        # For demonstration, we'll simulate a successful connection
        try:
            self.ser = serial.Serial(
                    self.serial_settings['port'],
                    int(self.serial_settings['baud_rate']),
                    timeout=0.05
                )
            # Perform any additional initialization if needed
            #send_command(self.ser, "reset")  # Setting the unit to (mm/s)
            start_time = time.time()
            response = read_response(self.ser)
            end_time = time.time()
            elapse_time = end_time - start_time
            print("start time: ", start_time)
            print("End time: ", end_time)
            print("Elapsed time: ", elapse_time)

            #self.update_motor_positions()
            # Create file to store motor positions
            self.motor_positions_file = open("motor_positions_file.csv", "w")
            self.motor_positions_file.write("time,X,Y,Z\n")
            self.motor_positions_file.close()
            self.start_position_thread(update_positions_function)
            
            
            self.controller_connect_action.setIcon(QIcon(resource_path('icons/disconnect_controller.png')))
            self.controller_connect_action.setText('Disconnect Controller')
            self.controller_connect_action.setStatusTip('Disconnect from the controller device')
            QMessageBox.information(self, "Connect", "Controller connected successfully.")
            self.controller_connected = True
        except Exception as e:
            self.controller_connect_action.setChecked(False)
            self.controller_connect_action.setIcon(QIcon(resource_path('icons/connect_controller.png')))
            QMessageBox.critical(self, "Connection Error", f"Failed to connect controller: {e}")

    
    def disconnectControllerDevice(self):
        # Implement your controller disconnection logic here
        try:
            # Simulate disconnection logic (replace with actual code)
            # Example: self.controller.disconnect()
            if hasattr(self, 'ser') and self.ser.is_open:
                send_command(self.ser, "stopspeed")
                self.position_thread.requestInterruption()
                time.sleep(0.4)
                #self.motor_positions_file.close()
                self.ser.close()
            
            self.controller_connect_action.setIcon(QIcon(resource_path('icons/connect_controller.png')))
            self.controller_connect_action.setText('Connect Controller')
            self.controller_connect_action.setStatusTip('Connect to the controller device')
            QMessageBox.information(self, "Disconnect", "Controller disconnected successfully.")
            self.controller_connected = False
        except Exception as e:
            self.controller_connect_action.setChecked(True)
            self.controller_connect_action.setIcon(QIcon(resource_path('icons/disconnect_controller.png')))
            QMessageBox.critical(self, "Disconnection Error", f"Failed to disconnect controller: {e}")

    def connectPotentiostatDevice(self):
        # Implement your potentiostat connection logic here
        try:
            self.connect_potentiostat()
        except Exception as e:
            self.potentiostat_connect_action.setChecked(False)
            self.potentiostat_connect_action.setIcon(QIcon(resource_path('icons/plug-connect.png')))
            QMessageBox.critical(self, "Connection Error", f"Failed to connect potentiostat: {e}")

    def disconnectPotentiostatDevice(self):
        # Implement your potentiostat disconnection logic here
        try:
            # Simulate disconnection logic (replace with actual code)
            # Example: self.potentiostat.disconnect()
            self.disconnect_potentiostat()
            self.potentiostat_connected = False
            self.potentiostat_connect_action.setIcon(QIcon(resource_path('icons/plug-connect.png')))
            self.potentiostat_connect_action.setText('Connect Potentiostat')
            self.potentiostat_connect_action.setStatusTip('Connect to the potentiostat device')
            QMessageBox.information(self, "Disconnect", "Potentiostat disconnected successfully.")
        except Exception as e:
            self.potentiostat_connect_action.setChecked(True)
            self.potentiostat_connect_action.setIcon(QIcon(resource_path('icons/plug-disconnect.png')))
            QMessageBox.critical(self, "Disconnection Error", f"Failed to disconnect potentiostat: {e}")

    def selectChannel(self, index):
        channel = self.channel_combo.currentText()
        # Implement your channel selection logic here
        #QMessageBox.information(self, "Channel Selection", f"Selected {channel}.")
    
    def start_position_thread(self, update_positions_name):
        self.position_thread = MotorPositionThread(self, update_positions_name)
        self.position_thread.position_values_signal.connect(self.update_position_values)
        self.position_thread.finished_signal.connect(self.update_position_finished)

        self.position_thread.start()

    
    def update_position_finished(self):
        QMessageBox.information(self, "Position update", "Motor position update is done.")

    def start_experiment(self, technique_function, is_seccm):
        self.experiment_thread = ExperimentThread(self, technique_function)
        if technique_function.__name__ == "perf_ca" and not is_seccm:
            self.experiment_thread.data_signal.connect(self.update_ca_output_data)
            self.experiment_thread.finished_signal.connect(self.on_approach_finished)
        elif technique_function.__name__ == "perf_seccm" and is_seccm:
            self.experiment_thread.seccm_approach_data_signal.connect(self.update_ca_output_data)
            self.experiment_thread.seccm_cv_data_signal.connect(self.update_cv_output_data)
            self.experiment_thread.seccm_cp_data_signal.connect(self.update_tech_cp_output_data)
            self.experiment_thread.seccm_ca_data_signal.connect(self.update_tech_ca_output_data)
            self.experiment_thread.seccm_retract_data_signal.connect(self.update_ca_output_data)
            self.experiment_thread.seccm_record_position_signal.connect(self.seccm_record_positions)
            self.experiment_thread.finished_signal.connect(self.on_seccm_finished)
        elif technique_function.__name__ == "perf_ca" and is_seccm:
            self.experiment_thread.data_signal.connect(self.update_ca_output_data)
            self.experiment_thread.finished_signal.connect(self.on_seccm_approach_finished)
            #self.seccm_approach_data = open("self.seccm_approach_data.csv", "w")
        elif technique_function.__name__ == "perf_cv" and is_seccm:
            self.experiment_thread.data_signal.connect(self.update_cv_output_data)
            self.experiment_thread.finished_signal.connect(self.on_seccm_cv_finished)
        elif technique_function.__name__ == "perf_cv" and not is_seccm:
            self.cv_Ewe.clear()
            self.cv_Iwe.clear()
            self.cv_time.clear()
            self.cv_cycle.clear()
            self.cv_local_time.clear()
            self.experiment_thread.data_signal.connect(self.update_cv_output_data)
            self.experiment_thread.finished_signal.connect(self.on_electro_cv_finished)
        elif technique_function.__name__ == "perf_peis" and not is_seccm:
            self.experiment_thread.data_signal_peis_1.connect(self.update_peis_1_output_data)
            self.experiment_thread.data_signal_peis_0.connect(self.update_peis_0_output_data)
            self.experiment_thread.finished_signal.connect(self.on_peis_finished)
        elif technique_function.__name__ == "perf_sicm" and not is_seccm:
            self.experiment_thread.data_signal.connect(self.update_sicm_output_data)
            self.experiment_thread.finished_signal.connect(self.on_sicm_finished)
        elif technique_function.__name__ == "perf_secm" and not is_seccm:
            self.experiment_thread.data_signal.connect(self.update_secm_output_data)
            self.experiment_thread.finished_signal.connect(self.on_secm_finished)
        elif technique_function.__name__ == "perf_abs_secm" and not is_seccm:
            self.experiment_thread.data_signal.connect(self.update_abs_secm_output_data)
            self.experiment_thread.secm_abs_cv_data_signal.connect(self.update_abs_secm_cv)
            self.experiment_thread.finished_signal.connect(self.on_abs_secm_finished)
        elif technique_function.__name__ == "perf_current_values" and not is_seccm:
            self.experiment_thread.current_values_signal.connect(self.update_current_values)
        elif technique_function.__name__ == "perf_current_values" and is_seccm:
            self.experiment_thread.current_values_signal.connect(self.update_current_values_seccm)
        elif technique_function.__name__ == "perf_line_scan" and not is_seccm:
            self.experiment_thread.data_signal.connect(self.update_ca_output_data)
            self.experiment_thread.finished_signal.connect(self.on_line_scan_finished)
        elif technique_function.__name__ == "perf_tech_ca" and not is_seccm:
            self.tech_ca_Ewe.clear()
            self.tech_ca_Iwe.clear()
            self.tech_ca_time.clear()
            self.tech_ca_cycle.clear()
            self.tech_ca_local_time.clear()
            self.experiment_thread.data_signal.connect(self.update_tech_ca_output_data)
            self.experiment_thread.finished_signal.connect(self.on_tech_ca_finished)
        elif technique_function.__name__ == "perf_tech_cp" and not is_seccm:
            self.tech_cp_Ewe.clear()
            self.tech_cp_Iwe.clear()
            self.tech_cp_time.clear()
            self.tech_cp_cycle.clear()
            self.tech_cp_local_time.clear()
            self.experiment_thread.data_signal.connect(self.update_tech_cp_output_data)
            self.experiment_thread.finished_signal.connect(self.on_tech_cp_finished)
        print("thread starting ....")
        self.experiment_thread.start()
    
    def stop_experiment(self):
        if hasattr(self, 'experiment_thread'):
            self.experiment_thread.stop()

    def on_approach_finished(self):
        self.single_approach_data = open("approach_data.csv", "w")
        self.single_approach_data.write("local_time,t (s),Ewe (V),I (A),Cycle (N)\n")
        # Iterate over the lists and write each row
        for lt, t, Ewe, Iwe, cycle in zip(self.ca_local_time,self.ca_time, self.ca_Ewe, self.ca_Iwe, self.ca_cycle):
            self.single_approach_data.write(f"{lt},{t},{Ewe},{Iwe},{cycle}\n")

        self.single_approach_data.write(f"\n\n")
        self.single_approach_data.close()
        print("data have been writted into approach_data.csv")
        self.ca_Ewe.clear()
        self.ca_Iwe.clear()
        self.ca_time.clear()
        self.ca_cycle.clear()
        self.ca_local_time.clear()

        
        # retarting the current values thread
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)
        # Message indiacating the seccm is done
        QMessageBox.information(self, "Approch scan Finished", "The approach scan has completed successfully.")
    
    def on_line_scan_finished(self):
        positions_data = pd.read_csv('motor_positions_file.csv', skiprows=[1])
        measurements_data = pd.read_csv('electro_line_scan_out.csv')

        positions_data['time'] = pd.to_datetime(positions_data['time'], format='%H:%M:%S')
        measurements_data['local_time'] = pd.to_datetime(measurements_data['local_time'], format='%H:%M:%S')
        first_value_secm = measurements_data["local_time"].values[0]
        last_value_secm = measurements_data["local_time"].values[-1]

        positions_data = positions_data[(positions_data['time'] >= first_value_secm) & (positions_data['time'] <=last_value_secm)]
        

        merge_data_secm = pd.merge(positions_data, measurements_data, left_on='time', right_on='local_time', how='inner')

        merge_data_secm.to_csv('electro_line_scan.csv', index=False)

        # retarting the current values thread
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        # Message indiacating the seccm is done
        QMessageBox.information(self, "Line Scan Finished", "The Line scan experiment has completed successfully.")


    def on_abs_secm_finished(self):
        positions_data = pd.read_csv('motor_positions_file.csv', skiprows=[1])
        measurements_data = pd.read_csv('electro_abs_secm_out.csv')
        
        positions_data['time'] = pd.to_datetime(positions_data['time'], format='%H:%M:%S')
        measurements_data['local_time'] = pd.to_datetime(measurements_data['local_time'], format='%H:%M:%S')
        first_value_secm = measurements_data["local_time"].values[0]
        last_value_secm = measurements_data["local_time"].values[-1]

        positions_data = positions_data[(positions_data['time'] >= first_value_secm) & (positions_data['time'] <=last_value_secm)]
        

        merge_data_secm = pd.merge(positions_data, measurements_data, left_on='time', right_on='local_time', how='inner')

        merge_data_secm.to_csv('electro_abs_secm_pos.csv', index=False)

        #print("data have been writted into electro_secm_out.csv")
        self.abs_secm_Ewe.clear()
        self.abs_secm_Iwe.clear()
        self.abs_secm_time.clear()
        self.abs_secm_cycle.clear()
        self.abs_secm_local_time.clear()

        self.abs_secm_cv_Ewe.clear()
        self.abs_secm_cv_Iwe.clear()
        self.abs_secm_cv_time.clear()
        self.abs_secm_cv_cycle.clear()
        self.abs_secm_cv_local_time.clear()

        # retarting the current values thread
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        # Message indiacating the seccm is done
        QMessageBox.information(self, "Abs SECM Finished", "The Abs SECM experiment has completed successfully.")
    

    def on_secm_finished(self):
        self.single_secm_data = open("electro_secm_out.csv", "w")
        self.single_secm_data.write("local_time,t (s),Ewe (V),I (A),Cycle (N)\n")
        # Iterate over the lists and write each row
        for lt,t, Ewe, Iwe, cycle in zip(self.secm_local_time,self.secm_time, self.secm_Ewe, self.secm_Iwe, self.secm_cycle):
            self.single_secm_data.write(f"{lt},{t},{Ewe},{Iwe},{cycle}\n")

        self.single_secm_data.write(f"\n\n")
        self.single_secm_data.close()
        positions_data = pd.read_csv('motor_positions_file.csv', skiprows=[1])
        measurements_data = pd.read_csv('electro_secm_out.csv')
        
        positions_data['time'] = pd.to_datetime(positions_data['time'], format='%H:%M:%S')
        measurements_data['local_time'] = pd.to_datetime(measurements_data['local_time'], format='%H:%M:%S')
        first_value_secm = measurements_data["local_time"].values[0]
        last_value_secm = measurements_data["local_time"].values[-1]

        positions_data = positions_data[(positions_data['time'] >= first_value_secm) & (positions_data['time'] <=last_value_secm)]
        

        merge_data_secm = pd.merge(positions_data, measurements_data, left_on='time', right_on='local_time', how='inner')

        merge_data_secm.to_csv('electro_secm_pos.csv', index=False)

        #print("data have been writted into electro_secm_out.csv")
        self.secm_Ewe.clear()
        self.secm_Iwe.clear()
        self.secm_time.clear()
        self.secm_cycle.clear()
        self.secm_local_time.clear()

        # retarting the current values thread
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        # Message indiacating the seccm is done
        QMessageBox.information(self, "SECM Finished", "The SECM experiment has completed successfully.")
    

    def on_sicm_finished(self):
        self.single_sicm_data = open("electro_sicm_out.csv", "w")
        self.single_sicm_data.write("local_time,t (s),Ewe (V),I (A),Cycle (N)\n")
        # Iterate over the lists and write each row
        for lt,t, Ewe, Iwe, cycle in zip(self.sicm_local_time,self.sicm_time, self.sicm_Ewe, self.sicm_Iwe, self.sicm_cycle):
            self.single_sicm_data.write(f"{lt},{t},{Ewe},{Iwe},{cycle}\n")

        self.single_sicm_data.write(f"\n\n")
        self.single_sicm_data.close()
        print("data have been writted into electro_sicm_out.csv")
        self.sicm_Ewe.clear()
        self.sicm_Iwe.clear()
        self.sicm_time.clear()
        self.sicm_cycle.clear()
        self.sicm_local_time.clear()

        # retarting the current values thread
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        # Message indiacating the seccm is done
        QMessageBox.information(self, "SICM Finished", "The SICM experiment has completed successfully.")
    
    
    def on_peis_finished(self):
        self.peis_Ewe_0.clear()
        self.peis_Iwe_0.clear()
        self.peis_time_0.clear()
        self.peis_Ewe_1.clear()
        self.peis_Iwe_1.clear()
        self.peis_time_1.clear()
        self.peis_f.clear()
        self.peis_phase_Zwe.clear()
        self.peis_phase_Zce.clear()
        self.peis_local_time.clear()
        self.peis_abs_Iwe_1.clear()
        self.peis_abs_Ewe_1.clear()
        self.peis_abs_Zwe_1.clear()
        self.peis_Zwe_real_1.clear()
        self.peis_Zwe_imag_1.clear()
        print("Peis thread finished done ...")
        #self.peis_cycle.clear()

        # retarting the current values thread
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)
        # Message indiacating the seccm is done
        QMessageBox.information(self, "PEIS Finished", "The PEIS experiment has completed successfully.")
        

    def on_seccm_approach_finished(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        self.seccm_approach_data = open("self.seccm_approach_data.csv", "a+")

        # Iterate over the lists and write each row
        for lt, t, Ewe, Iwe, cycle in zip(self.ca_local_time,self.ca_time, self.ca_Ewe, self.ca_Iwe, self.ca_cycle):
            self.seccm_approach_data.write(f"{lt},{t},{Ewe},{Iwe},{cycle}\n")

        self.seccm_approach_data.write(f"\n\n")
        self.seccm_approach_data.close()
        self.ca_Ewe.clear()
        self.ca_Iwe.clear()
        self.ca_time.clear()
        self.ca_cycle.clear()
        self.ca_local_time.clear()

        if self.first:
            self.i = 1
            self.j = 1
            self.first = False
            # CV datadump, writing in all the positions and their cv in a same file.
            self.seccm_datadump = open("self.seccm_datadump.csv", "w")


        # stop motor position thread
        #time.sleep(1)
        #self.position_thread.requestInterruption()
        #self.write_seccm_position = True

       
        # restart motor position thread
        #self.start_position_thread(update_positions_function)

        # perform the first CV
        #self.update_motor_positions()
        if self.seccm_options['tech_measure'] == 'CV':
            self.start_experiment(perf_cv, True)
        
         # write the first position coordinates
        #send_command(self.ser, "pos")
        x_pos, y_pos, z_pos = self.x_input.text(), self.y_input.text(), self.z_input.text()
        self.seccm_datadump.write(f"x: {x_pos}, y: {y_pos:}, z:{z_pos:}\n")
        self.seccm_datadump.write("local_time,t (s),Ewe (V),I (A),Cycle (N)\n")
        self.seccm_datadump.flush()

    
    def on_tech_cp_finished(self):
        self.update_graphic_display()
        # Message indiacating the cp is done
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        QMessageBox.information(self, "CP Finished", "The CP experiment has completed successfully.")
    

    def on_tech_ca_finished(self):
        self.update_graphic_display()
        # Message indiacating the ca is done
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        QMessageBox.information(self, "CA Finished", "The CA experiment has completed successfully.")
    
    def on_electro_cv_finished(self):

        # Message indiacating the cv is done
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        QMessageBox.information(self, "CV Finished", "The CV experiment has completed successfully.")

    def on_seccm_finished(self):
        # TODO: combined the seccm_positions_file with the seccm_cv_file

        # Message indiacating the seccm is done
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, False)

        QMessageBox.information(self, "seccm Finished", "The seccm experiment has completed successfully.")

    
    def on_seccm_cv_finished(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return

        
        # Iterate over the lists and write each row
        for lt, t, Ewe, Iwe, cycle in zip(self.cv_local_time,self.cv_time, self.cv_Ewe, self.cv_Iwe, self.cv_cycle):
            self.seccm_datadump.write(f"{lt},{t},{Ewe},{Iwe},{cycle}\n")

        self.seccm_datadump.write(f"\n\n")
        self.cv_Ewe.clear()
        self.cv_Iwe.clear()
        self.cv_time.clear()
        self.cv_cycle.clear()
        self.cv_local_time.clear()

        # retarting the current values thread
        self.retract_values_file = open("retract_values_file.csv", "+a")
        self.retract_values_file.write("\nlocal_time,state,Ewe (V),I (A)\n")
        if self.potentiostat_connected:
            self.start_experiment(perf_current_values, True)

        if self.i == self.number_of_steps and self.j == self.number_of_steps:
            self.seccm_datadump.close()
            #with the retract_h
            with self.write_lock:
                send_command(self.ser, f"-{self.seccm_options['retract_h']} 3 speed")
            time.sleep(1)
            with self.write_lock:
                send_command(self.ser, "stopspeed")
            # Get the tip up to 15 um
            #send_command(self.ser, "-0.005 3 speed")
            #time.sleep(3)
            #send_command(self.ser, "stopspeed")
            # Message indiacating the seccm is done
            if self.potentiostat_connected:
                self.start_experiment(perf_current_values, False)

            QMessageBox.information(self, "seccm Finished", "The seccm experiment has completed successfully.")
            return
        else:
            #with the retract_h
            with self.write_lock:
                send_command(self.ser, f"-{self.seccm_options['retract_h']} 3 speed")
            time.sleep(1)
            with self.write_lock:
                send_command(self.ser, "stopspeed")
            # Get the tip up to 10 um
            #send_command(self.ser, "-0.005 3 speed")
            #time.sleep(3)
            #send_command(self.ser, "stopspeed")

            if self.j < self.number_of_steps:
                # Move to the next X position
                if(self.right):
                    with self.write_lock:
                        send_command(self.ser, self.x_move_r)
                    time.sleep(1)
                    with self.write_lock:
                        send_command(self.ser, "stopspeed")
                else:
                    with self.write_lock:
                        send_command(self.ser, self.x_move_l)
                    time.sleep(1)
                    with self.write_lock:
                        send_command(self.ser, "stopspeed")

                """TODO: perform the approach with basic parameters
                        speed = 100 nm/s, estimated_time = 2min30s
                        spike_treshold = 30e-12 A, volt_applied = 0.5
                """
                self.j = self.j + 1
                self.experiment_thread.requestInterruption()
                self.approach_options['estimated_approach_time'] = str(3000)
                self.start_experiment(perf_ca, True)
            elif self.j == self.number_of_steps and self.i < self.number_of_steps:
                with self.write_lock:
                    send_command(self.ser, self.y_move)
                time.sleep(1)
                with self.write_lock:
                    send_command(self.ser, "stopspeed")
                self.j = 1
                self.i = self.i + 1
                if self.right:
                    self.right = False
                else:
                    self.right = True
                
                """TODO: perform the approach with basic parameters
                        speed = 100 nm/s, estimated_time = 2min30s
                        spike_treshold = 30e-12 A, volt_applied = 0.5
                """
                self.experiment_thread.requestInterruption()
                self.approach_options['estimated_approach_time'] = str(3000)
                self.start_experiment(perf_ca, True)

    def on_experiment_finished(self):
        # Handle experiment completion (e.g., enable UI elements)

        self.ca_Ewe.clear()
        self.ca_Iwe.clear()
        self.ca_time.clear()
        self.ca_cycle.clear()

        self.cv_Ewe.clear()
        self.cv_Iwe.clear()
        self.cv_time.clear()
        self.cv_cycle.clear()

        #self.show_auto_close_message()
        # retarting the current values thread
        self.start_experiment(perf_current_values, False)
        #QMessageBox.information(self, "A measurement Finished", "A measurement session has completed successfully.")

    def show_auto_close_message(parent=None, title="A Measurement Finished", message="A measurement session has completed successfully.", timeout=5):
        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setStandardButtons(QMessageBox.NoButton)  # No buttons
        
        msg_box.show()  # Show the message box non-modally
        
        # Set up the timer to close the message box after 'timeout' milliseconds
        QTimer.singleShot(timeout, msg_box.close)
        

    def create_histogram_dock(self):
        self.histogram_dock = QDockWidget("2D Color Histogram", self)
        self.histogram_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.histogram_dock.visibilityChanged.connect(self.histogram_visibility_changed)

        # Create a pyqtgraph PlotWidget and add an ImageItem for 2D data
        histogram_widget = QWidget()
        histogram_layout = QVBoxLayout()
        self.histogram_plot = pg.PlotWidget()
        # (Optional: remove axis labels, set range, etc.)
        self.histogram_image = pg.ImageItem()
        self.histogram_plot.addItem(self.histogram_image)
        histogram_layout.addWidget(self.histogram_plot)
        histogram_widget.setLayout(histogram_layout)
        self.histogram_dock.setWidget(histogram_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.histogram_dock)

        # Add the dock widget to the main window
        self.addDockWidget(Qt.RightDockWidgetArea, self.histogram_dock)
        self.update_histogram()

    def create_graphic_display_dock(self):
        self.graphic_display_dock = QDockWidget("Graphic Display", self)
        self.graphic_display_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.graphic_display_dock.visibilityChanged.connect(self.graphic_display_visibility_changed)

        # Create a pyqtgraph PlotWidget for displaying data
        graphic_display_widget = QWidget()
        graphic_layout = QVBoxLayout()
        graphic_layout.setContentsMargins(0, 0, 0, 0)

        # File selection area
        file_selection_box = self.create_graphic_file_selection_box()

        # Data source selection
        data_source_box = self.create_graphic_data_source_box()

        # Axis selection
        axis_selector_box = self.create_axis_selector_box()

        # Instead of a FigureCanvas, use a PlotWidget
        self.graphic_display_plot = pg.PlotWidget()
        # (Optionally set title, grid, etc.)
        self.graphic_display_plot.setTitle("Graphic Display")
        self.graphic_display_plot.showGrid(x=True, y=True)
        # Create an initially empty curve and store the reference.
        self.graphic_curve = self.graphic_display_plot.plot([], pen='b')

        graphic_layout.addWidget(file_selection_box)
        graphic_layout.addWidget(data_source_box)
        graphic_layout.addWidget(axis_selector_box)
        graphic_layout.addWidget(self.graphic_display_plot)
        graphic_display_widget.setLayout(graphic_layout)
        self.graphic_display_dock.setWidget(graphic_display_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.graphic_display_dock)

        # Create a QTimer to update the graphic display at fixed intervals.
        self.graphic_update_timer = QTimer()
        self.graphic_update_timer.setInterval(5)  # update every 5 ms
        self.graphic_update_timer.timeout.connect(self.update_graphic_display)
        self.graphic_update_timer.start()

    def create_graphic_file_selection_box(self):
        group_box = QGroupBox()
        layout = QHBoxLayout()

        self.graphic_file_path_edit = QLineEdit()
        self.graphic_file_path_edit.setReadOnly(True)
        self.select_graphic_file_button = QPushButton('Select File')
        self.select_graphic_file_button.clicked.connect(self.select_graphic_file)

        layout.addWidget(self.graphic_file_path_edit)
        layout.addWidget(self.select_graphic_file_button)
        group_box.setLayout(layout)

        size_policy = group_box.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Fixed)
        group_box.setSizePolicy(size_policy)
        return group_box

    def create_graphic_data_source_box(self):
        group_box = QGroupBox()
        layout = QHBoxLayout()

        self.graphic_radio_live = QRadioButton('Live Experiment')
        self.graphic_radio_file = QRadioButton('From File')
        self.graphic_radio_live.setChecked(True)

        self.graphic_radio_live.toggled.connect(self.update_plot_source)
        self.graphic_radio_file.toggled.connect(self.update_plot_source)

        layout.addWidget(self.graphic_radio_live)
        layout.addWidget(self.graphic_radio_file)
        group_box.setLayout(layout)

        size_policy = group_box.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Fixed)
        group_box.setSizePolicy(size_policy)
        return group_box


    def update_plot_source(self):
        self.update_axis_selectors()
        self.update_graphic_display()


    def select_graphic_file(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Data File",
            "",
            "CSV Files (*.csv);;JSON Files (*.json);;All Files (*)",
            options=options
        )
        if file_name:
            self.graphic_file_path_edit.setText(file_name)
            self.load_graphic_data_from_file(file_name)


    def load_graphic_data_from_file(self, file_name):

        self.graphic_file_headers = []
        self.graphic_file_data = {}
        try:
            if file_name.endswith('.csv'):
                with open(file_name, 'r') as file:
                    reader = csv.reader(file)
                    self.graphic_file_headers = next(reader)  # Read headers
                    data_rows = list(reader)
                    # Determine which columns are numeric
                    numeric_columns = []
                    for i, header in enumerate(self.graphic_file_headers):
                        # Try converting the first non-empty value to float
                        for row in data_rows:
                            if len(row) <= i:
                                continue  # Skip if row doesn't have this column
                            value = row[i]
                            if value.strip() != '':
                                try:
                                    float(value)
                                    numeric_columns.append(i)
                                    break
                                except ValueError:
                                    break  # Non-numeric column
                    # Load data for numeric columns
                    for i in numeric_columns:
                        header = self.graphic_file_headers[i]
                        self.graphic_file_data[header] = []
                        for row in data_rows:
                            if len(row) <= i:
                                self.graphic_file_data[header].append(None)
                            else:
                                value = row[i]
                                if value.strip() == '':
                                    self.graphic_file_data[header].append(None)
                                else:
                                    try:
                                        self.graphic_file_data[header].append(float(value))
                                    except ValueError:
                                        self.graphic_file_data[header].append(None)
                    # Update headers to only include numeric columns
                    self.graphic_file_headers = [self.graphic_file_headers[i] for i in numeric_columns]
            elif file_name.endswith('.json'):
                with open(file_name, 'r') as file:
                    data = json.load(file)
                    results = data.get('results', {})
                    # Initialize variables
                    data_length = None
                    # Iterate over keys to determine numeric columns
                    for key, values in results.items():
                        if not isinstance(values, list):
                            continue  # Skip if not a list
                        # Check if values are numeric
                        numeric_values = []
                        is_numeric = True
                        for value in values:
                            try:
                                numeric_value = float(value)
                                numeric_values.append(numeric_value)
                            except (ValueError, TypeError):
                                is_numeric = False
                                break
                        if is_numeric:
                            # Ensure all columns have the same length
                            if data_length is None:
                                data_length = len(numeric_values)
                            elif len(numeric_values) != data_length:
                                is_numeric = False  # Skip columns with inconsistent lengths
                        if is_numeric:
                            self.graphic_file_data[key] = numeric_values
                self.file_headers = list(self.graphic_file_data.keys())
            else:
                QMessageBox.warning(self, "Unsupported Format", "The selected file format is not supported.")
                return

            if not self.graphic_file_headers:
                QMessageBox.warning(self, "No Numeric Data", "The selected file contains no numeric data to plot.")
                return

            # Update axis selectors if 'From File' is selected
            if self.graphic_radio_file.isChecked():
                self.update_axis_selectors()
                self.update_graphic_display()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load data from file: {e}")



    def update_axis_selectors(self):
        if self.graphic_radio_live.isChecked():
            # Use live data variables
            variables = list(self.available_axis_variables.keys())
        elif self.graphic_radio_file.isChecked():
            # Use variables from the file
            variables = self.graphic_file_headers
        else:
            variables = []

        # Update axis selectors
        self.x_axis_selector.blockSignals(True)
        self.y_axis_selector.blockSignals(True)

        self.x_axis_selector.clear()
        self.x_axis_selector.addItems(variables)
        self.y_axis_selector.clear()
        self.y_axis_selector.addItems(variables)

        self.x_axis_selector.blockSignals(False)
        self.y_axis_selector.blockSignals(False)



    def create_axis_selector_box(self):
        group_box = QGroupBox('Select Axes')
        layout = QHBoxLayout()

        # X-axis selection
        x_label = QLabel('X-axis')
        self.x_axis_selector = QComboBox()
        self.x_axis_selector.addItems(self.available_axis_variables.keys())
        self.x_axis_selector.currentIndexChanged.connect(self.update_graphic_display)

        # Y-axis selection
        y_label = QLabel('Y-axis')
        self.y_axis_selector = QComboBox()
        self.y_axis_selector.addItems(self.available_axis_variables.keys())
        self.y_axis_selector.setCurrentIndex(2) # default Y axis to 'Iwe (A)'
        self.y_axis_selector.currentIndexChanged.connect(self.update_graphic_display)

        # Add widgets to layout
        layout.addWidget(x_label)
        layout.addWidget(self.x_axis_selector)
        layout.addWidget(y_label)
        layout.addWidget(self.y_axis_selector)

        group_box.setLayout(layout)

        size_policy = group_box.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Fixed)
        group_box.setSizePolicy(size_policy)
        return group_box

    def toggle_histogram_visibility(self):
        visible = self.histogram_check.isChecked()
        self.histogram_dock.setVisible(visible)

    def toggle_graphic_display_visibility(self):
        visible = self.graphic_display_check.isChecked()
        self.graphic_display_dock.setVisible(visible)

    def histogram_visibility_changed(self, visible):
        self.histogram_check.setChecked(visible)

    def graphic_display_visibility_changed(self, visible):
        self.graphic_display_check.setChecked(visible)

    def update_histogram(self):
        # Here self.data should be a 2D numpy array
        data = np.random.rand(10, 10)
        self.histogram_image.setImage(data, autoLevels=True)

    def update_graphic_display(self):

        x_var_name = self.x_axis_selector.currentText()
        y_var_name = self.y_axis_selector.currentText()

        if self.graphic_radio_live.isChecked():
            x_var = self.get_variable_data(x_var_name, source='live')
            y_var = self.get_variable_data(y_var_name, source='live')
        elif self.graphic_radio_file.isChecked():
            x_var = self.get_variable_data(x_var_name, source='file')
            y_var = self.get_variable_data(y_var_name, source='file')
        else:
            return

        """if not x_var or not y_var:
            return  # No data to plot

        # Remove pairs where either x or y is None
        x_var_filtered, y_var_filtered = zip(*[
            (x, y) for x, y in zip(x_var, y_var) if x is not None and y is not None
        ])

        if not x_var_filtered or not y_var_filtered:
            QMessageBox.warning(self, "No Data", "No valid data points to plot.")
            return"""
        
        """try:
            x_var_filtered, y_var_filtered = zip(*[(x, y) for x, y in zip(x_var, y_var)
                                                if x is not None and y is not None])
        except ValueError:
            # Not enough data
            return"""
        
         # If there is no data, do nothing.
        if x_var.size == 0 or y_var.size == 0:
            return
        
        # If the data arrays differ in length, plot up to the minimum available points.
        N = min(len(x_var), len(y_var))
        x_var = x_var[-N:]
        y_var = y_var[-N:]

        # Update the persistent curve with the new data.
        self.graphic_curve.setData(x_var, y_var)
        
        # Update axis labels and title based on the selected variables.
        self.graphic_display_plot.setLabel('bottom', x_var_name)
        self.graphic_display_plot.setLabel('left', y_var_name)
        self.graphic_display_plot.setTitle(f'{y_var_name} vs {x_var_name}')
    

        #self.graphic_display_plot.clear()
        # Instead of clearing and re-plotting, update the existing curve.
        """self.graphic_curve.setData(x_var_filtered, y_var_filtered)
        self.graphic_display_plot.plot(x_var_filtered, y_var_filtered, pen='b')
        self.graphic_display_plot.setLabel('bottom', x_var_name)
        self.graphic_display_plot.setLabel('left', y_var_name)
        self.graphic_display_plot.setTitle(f'{y_var_name} vs {x_var_name}')"""




    """    def update_live_data(self, new_time, new_Ewe, new_Iwe):
        self.data_time.append(new_time)
        self.data_Ewe.append(new_Ewe)
        self.data_Iwe.append(new_Iwe)

        if self.graphic_radio_live.isChecked():
            self.update_graphic_display()"""


    def get_variable_data(self, var_name, source='live'):
        if source == 'live':
            # Look up the internal key from the available axis dictionary.
            key = self.available_axis_variables.get(var_name, var_name)
            # For live data, return the numpy array from the buffer.
            return np.array(self.plot_buffer.get(key, []))
        
            """if var_name == 'Time (s)':
                return self.data_time
            elif var_name == 'Ewe (V)':
                return self.data_Ewe
            elif var_name == 'Iwe (A)':
                return self.data_Iwe
            elif var_name == 'Phase Zwe':
                return self.data_phase_Zwe
            elif var_name == 'Phase Zce':
                return self.data_phase_Zce
            elif var_name == 'f (Hz)':
                return self.data_f
            elif var_name == '|Ewe| (V)':
                return self.data_abs_Ewe
            elif var_name == '|Iwe| (A)':
                return self.data_abs_Iwe
            elif var_name == '|Zwe|':
                return self.data_abs_Zwe
            elif var_name == 'Re(Zwe)':
                return self.data_Zwe_real
            elif var_name == 'Img(Zwe)':
                return self.data_Zwe_imag
            elif var_name == 'Phase deg(Zwe)':
                return self.data_phase_Zwe_deg
            elif var_name == 'log(f)':
                return self.data_log_f
            else:
                return []"""
        elif source == 'file':
            return self.graphic_file_data.get(var_name, [])
        else:
            return []


    def reset_plot_buffer(self):
        """Clear all buffers so that data from different experiments don't mix."""
        for key in self.plot_buffer:
            self.plot_buffer[key].clear()
        # Optionally, also update the plot to show an empty graph.
        self.graphic_curve.setData([], [])
        print("Buffers cleared.")

    def update_plots_measurements(self, new_data):
        # Update the data
        self.data = new_data
        # Update the histogram
        self.update_histogram()
        # Update the graphic display
        self.update_graphic_display()

    def seccm_record_positions(self, record, lt):
        self.seccm_positions_file = open("seccm_positions_file.csv", "a+")
        x_pos, y_pos, z_pos = self.x_input.text(), self.y_input.text(), self.z_input.text()
        self.seccm_positions_file.write(f"local_time: {lt}, x: {x_pos}, y: {y_pos:}, z:{z_pos:}\n")
        self.seccm_positions_file.close()

        
        # Clear the approach, cv, retract lists
        self.ca_Ewe.clear()
        self.ca_Iwe.clear()
        self.ca_time.clear()
        self.ca_cycle.clear()
        self.ca_local_time.clear()

        self.cv_Ewe.clear()
        self.cv_Iwe.clear()
        self.cv_time.clear()
        self.cv_cycle.clear()
        self.cv_local_time.clear()

        self.tech_cp_Ewe.clear()
        self.tech_cp_Iwe.clear()
        self.tech_cp_time.clear()
        self.tech_cp_cycle.clear()
        self.tech_cp_local_time.clear()

        self.tech_ca_Ewe.clear()
        self.tech_ca_Iwe.clear()
        self.tech_ca_time.clear()
        self.tech_ca_cycle.clear()
        self.tech_ca_local_time.clear()

        if 'CA' in self.seccm_options['tech_measure']:
            self.update_graphic_display() 
        if 'CP' in self.seccm_options['tech_measure']:
            self.update_graphic_display() 




    def update_tech_cp_output_data(self, Ewe, Iwe, t_ime, cycle, lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.tech_cp_Ewe.append(Ewe)
        self.tech_cp_Iwe.append(Iwe)
        self.tech_cp_time.append(t_ime)
        self.tech_cp_cycle.append(cycle)
        self.tech_cp_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.tech_cp_time
        self.data_Ewe = self.tech_cp_Ewe
        self.data_Iwe = self.tech_cp_Iwe
        start_time = time.time()
        self.update_graphic_display()
        end_time = time.time()
        elapse_time = end_time - start_time
        print("start time: ", start_time)
        print("End time: ", end_time)
        print("Elapsed time: ", elapse_time)"""
        #self.update_motor_positions()

    def update_tech_ca_output_data(self, Ewe, Iwe, t_ime, cycle, lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.tech_ca_Ewe.append(Ewe)
        self.tech_ca_Iwe.append(Iwe)
        self.tech_ca_time.append(t_ime)
        self.tech_ca_cycle.append(cycle)
        self.tech_ca_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.tech_ca_time
        self.data_Ewe = self.tech_ca_Ewe
        self.data_Iwe = self.tech_ca_Iwe
        self.update_graphic_display()"""
        #self.update_motor_positions()

    def update_ca_output_data(self, Ewe, Iwe, t_ime, cycle, lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.ca_Ewe.append(Ewe)
        self.ca_Iwe.append(Iwe)
        self.ca_time.append(t_ime)
        self.ca_cycle.append(cycle)
        self.ca_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.ca_time
        self.data_Ewe = self.ca_Ewe
        self.data_Iwe = self.ca_Iwe
        self.update_graphic_display()"""
        #self.update_motor_positions()

    def update_sicm_output_data(self, Ewe, Iwe, t_ime, cycle,lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.sicm_Ewe.append(Ewe)
        self.sicm_Iwe.append(Iwe)
        self.sicm_time.append(t_ime)
        self.sicm_cycle.append(cycle)
        self.sicm_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.sicm_time
        self.data_Ewe = self.sicm_Ewe
        self.data_Iwe = self.sicm_Iwe
        start_time = time.time()
        self.update_graphic_display()
        end_time = time.time()
        elapse_time = end_time - start_time
        print("start time: ", start_time)
        print("End time: ", end_time)
        print("Elapsed time: ", elapse_time)"""
        #self.update_motor_positions()

    def update_abs_secm_cv(self, Ewe, Iwe, t_ime, cycle,lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.abs_secm_cv_Ewe.append(Ewe)
        self.abs_secm_cv_Iwe.append(Iwe)
        self.abs_secm_cv_time.append(t_ime)
        self.abs_secm_cv_cycle.append(cycle)
        self.abs_secm_cv_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.abs_secm_cv_time
        self.data_Ewe = self.abs_secm_cv_Ewe
        self.data_Iwe = self.abs_secm_cv_Iwe
        self.update_graphic_display()"""
        #self.update_motor_positions()

    def update_abs_secm_output_data(self, Ewe, Iwe, t_ime, cycle,lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.abs_secm_Ewe.append(Ewe)
        self.abs_secm_Iwe.append(Iwe)
        self.abs_secm_time.append(t_ime)
        self.abs_secm_cycle.append(cycle)
        self.abs_secm_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.abs_secm_time
        self.data_Ewe = self.abs_secm_Ewe
        self.data_Iwe = self.abs_secm_Iwe
        self.update_graphic_display()"""
        #self.update_motor_positions()

    def update_secm_output_data(self, Ewe, Iwe, t_ime, cycle,lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.secm_Ewe.append(Ewe)
        self.secm_Iwe.append(Iwe)
        self.secm_time.append(t_ime)
        self.secm_cycle.append(cycle)
        self.secm_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        
        """self.data_time = self.secm_time
        self.data_Ewe = self.secm_Ewe
        self.data_Iwe = self.secm_Iwe
        self.update_graphic_display()"""
        #self.update_motor_positions()

    def update_cv_output_data(self, Ewe, Iwe, t_ime, cycle, lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

        self.cv_Ewe.append(Ewe)
        self.cv_Iwe.append(Iwe)
        self.cv_time.append(t_ime)
        self.cv_cycle.append(cycle)
        self.cv_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)

        """self.data_time = self.cv_time
        self.data_Ewe = self.cv_Ewe
        self.data_Iwe = self.cv_Iwe
        self.update_graphic_display()"""
        #self.update_motor_positions()

    def update_peis_0_output_data(self, Ewe, Iwe, t_ime, lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')
        
        self.peis_Ewe_0.append(Ewe)
        self.peis_Iwe_0.append(Iwe)
        self.peis_time_0.append(t_ime)
        self.peis_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)

        """self.data_time = self.peis_time_0
        self.data_Ewe = self.peis_Ewe_0
        self.data_Iwe = self.peis_Iwe_0
        self.update_graphic_display()"""
        #print("update display done ...")

    def update_peis_1_output_data(self, f, abs_Ewe, abs_Iwe, phase_Zwe,  Ewe, Iwe, phase_Zce, t_ime, abs_Zwe, Zwe_real, Zwe_imag,phase_Zwe_deg,log_f, lt):
        self.current_i_value = Iwe
        self.current_ewe_value = Ewe
        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')
        
        
        self.peis_Ewe_1.append(Ewe)
        self.peis_Iwe_1.append(Iwe)
        self.peis_time_1.append(t_ime)
        self.peis_phase_Zwe.append(phase_Zwe)
        self.peis_phase_Zce.append(phase_Zce)
        self.peis_f.append(f)
        self.peis_abs_Zwe_1.append(abs_Zwe)
        self.peis_Zwe_real_1.append(Zwe_real)
        self.peis_Zwe_imag_1.append(Zwe_imag)
        self.peis_abs_Iwe_1.append(abs_Iwe)
        self.peis_abs_Ewe_1.append(abs_Ewe)
        self.peis_phase_Zwe_deg_1.append(phase_Zwe_deg)
        self.peis_log_f_1.append(log_f)
        self.peis_local_time.append(lt)

        self.plot_buffer['time'].append(t_ime)
        self.plot_buffer['Iwe'].append(Iwe)
        self.plot_buffer['Ewe'].append(Ewe)
        self.plot_buffer['f'].append(f)
        self.plot_buffer['abs_Ewe'].append(abs_Ewe)
        self.plot_buffer['abs_Iwe'].append(abs_Iwe)
        self.plot_buffer['abs_Zwe'].append(abs_Zwe)
        self.plot_buffer['Zwe_real'].append(Zwe_real)
        self.plot_buffer['Zwe_imag'].append(Zwe_imag)
        self.plot_buffer['phase_Zwe'].append(phase_Zwe)
        self.plot_buffer['phase_Zce'].append(phase_Zce)
        self.plot_buffer['phase_Zwe_deg'].append(phase_Zwe_deg)
        self.plot_buffer['log_f'].append(log_f)


        """self.data_time = self.peis_time_1
        self.data_Ewe = self.peis_Ewe_1
        self.data_Iwe = self.peis_Iwe_1
        self.data_f = self.peis_f
        self.data_phase_Zwe = self.peis_phase_Zwe
        self.data_phase_Zce = self.peis_phase_Zce
        self.data_abs_Ewe = self.peis_abs_Ewe_1
        self.data_abs_Iwe = self.peis_abs_Iwe_1
        self.data_abs_Zwe = self.peis_abs_Zwe_1
        self.data_Zwe_real = self.peis_Zwe_real_1
        self.data_Zwe_imag = self.peis_Zwe_imag_1
        self.data_phase_Zwe_deg = self.peis_phase_Zwe_deg_1
        self.data_log_f = self.peis_log_f_1
        self.update_graphic_display()"""
        #print("update display done ...")
        

    def create_menus(self):
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu('File')

        # Save result action in file menu bar
        save_result_action = QAction('Save results', self)
        save_result_action.triggered.connect(self.save_result_file)
        file_menu.addAction(save_result_action)

        # Setup Menu
        setup_menu = menubar.addMenu('Set up')

        controller_action = QAction('Hardware set up', self)
        controller_action.triggered.connect(self.controller_setup)
        setup_menu.addAction(controller_action)

        serial_action = QAction('Serial Port', self)
        serial_action.triggered.connect(self.serial_setup)
        setup_menu.addAction(serial_action)

        reboot_controller_action = QAction('Reboot Controller', self)
        reboot_controller_action.triggered.connect(self.reboot_controller_setup)
        setup_menu.addAction(reboot_controller_action)

        # View Menu
        view_menu = menubar.addMenu('View')

        self.histogram_check = QAction('2D Color Histogram', self, checkable=True)
        self.histogram_check.setChecked(False)  # Default to checked
        self.histogram_check.triggered.connect(self.toggle_histogram_visibility)
        view_menu.addAction(self.histogram_check)

        self.graphic_display_check = QAction('Graphic Display', self, checkable=True)
        self.graphic_display_check.setChecked(True)  # Default to checked
        self.graphic_display_check.triggered.connect(self.toggle_graphic_display_visibility)
        view_menu.addAction(self.graphic_display_check)

        # Help Menu
        help_menu = menubar.addMenu('Help')

        user_manual_action = QAction("User's manual", self)
        user_manual_action.triggered.connect(lambda: self.open_pdf('documentation.md'))
        help_menu.addAction(user_manual_action)

        controller_manual_action = QAction('Corvus controller manual', self)
        controller_manual_action.triggered.connect(lambda: self.open_pdf('Corvus_Manual_EN_2_2.pdf'))
        help_menu.addAction(controller_manual_action)

        venus_commands_action = QAction('Venus-1 commands', self)
        venus_commands_action.triggered.connect(lambda: self.open_pdf('Corvus_Venus_eng_2_1.pdf'))
        help_menu.addAction(venus_commands_action)

        gp_user_manual = QAction('Graphical Display user manual', self)
        gp_user_manual.triggered.connect(lambda: self.open_url('https://pyqtgraph.readthedocs.io/en/latest/user_guide/index.html'))
        help_menu.addAction(gp_user_manual)

        # Channel Menu
        
    

    def save_result_file(self):
        options = QFileDialog.Options()
        options  |= QFileDialog.DontUseNativeDialog
        file_name,_ = QFileDialog.getSaveFileName(self,"Save Results", "", "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)", options=options)
        
        if file_name:
            try:
                # TODO Determine which results to save

                self.write_results_to_file(file_name)
                QMessageBox.information(self, "Save results", f"Saving results to {file_name} done successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occured while saving the results:\n{e}")


    def write_results_to_file(self, file_name):
        # Which technique data to save
        # At the moment based on the technique selector currentText
        technique = self.technique_selector.currentText()
        if technique == 'Approach Scan':
            data = {
                'Time (s)': self.ca_time,
                'Ewe (V)': self.ca_Ewe,
                'Iwe (A)': self.ca_Iwe,
                'Cycle (N)' : self.ca_cycle,
            }
            
            f_name = "approach_data.csv"
            with open(f_name) as approach_scan_file:
                data_approach = csv.reader(approach_scan_file, delimiter=',')
                f = open(file_name, 'w', newline='')
                with f:
                    writer = csv.writer(f)
                    for line in data_approach:
                        writer.writerow(line)
        elif technique == 'SICM':
            data = {
                'Time (s)': self.sicm_time,
                'Ewe (V)': self.sicm_Ewe,
                'Iwe (A)': self.sicm_Iwe,
                'Cycle (N)' : self.sicm_cycle,
            }
            f_name = "electro_sicm_out.csv"
            with open(f_name) as sicm_file:
                data_sicm = csv.reader(sicm_file, delimiter=',')
                f = open(file_name, 'w', newline='')
                with f:
                    writer = csv.writer(f)
                    for line in data_sicm:
                        writer.writerow(line)
        elif technique == 'SECM':
            data = {
                'Time (s)': self.secm_time,
                'Ewe (V)': self.secm_Ewe,
                'Iwe (A)': self.secm_Iwe,
                'Cycle (N)' : self.secm_cycle,
            }
            f_name = "electro_secm_out.csv"
            with open(f_name) as secm_file:
                data_secm = csv.reader(secm_file, delimiter=',')
                f = open(file_name, 'w', newline='')
                with f:
                    writer = csv.writer(f)
                    for line in data_secm:
                        writer.writerow(line)
        elif technique == 'Line Scan':
            data = {
                'Time (s)': self.ca_time,
                'Ewe (V)': self.ca_Ewe,
                'Iwe (A)': self.ca_Iwe,
                'Cycle (N)' : self.ca_cycle,
            }
        elif technique == 'Cyclic Voltammetry-CV':
            data = {
                'Time (s)': self.cv_time,
                'Ewe (V)': self.cv_Ewe,
                'Iwe (A)': self.cv_Iwe,
                'Cycle (N)' : self.cv_cycle,
            }
            f_name = "cv.csv"
            with open(f_name) as cv_file:
                data_cv = csv.reader(cv_file, delimiter=',')
                f = open(file_name, 'w', newline='')
                with f:
                    writer = csv.writer(f)
                    for line in data_cv:
                        writer.writerow(line)

        elif technique == 'SECCM':
            data = {
                'Time (s)': self.cv_time,
                'Ewe (V)': self.cv_Ewe,
                'Iwe (A)': self.cv_Iwe,
                'Cycle (N)' : self.cv_cycle,
            }
            f_name = "self.seccm_datadump.csv"
            with open(f_name) as seccm_file:
                data_seccm = csv.reader(seccm_file, delimiter=',')
                f = open(file_name, 'w', newline='')
                with f:
                    writer = csv.writer(f)
                    for line in data_seccm:
                        writer.writerow(line)

        elif technique == 'PEIS':
            data = {
                'Time (s)': self.peis_time_1,
                'Ewe (V)': self.peis_Ewe_1,
                'Iwe (A)': self.peis_Iwe_1,
            }
        else:
            QMessageBox.warning(self, 'Save Results', 'No data available to save for the selected technique')
            return
        
        # Write the data to the file
        """with open(file_name, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            #write the header
            headers = data.keys()
            #write data rows
            rows = zip(*data.values())
            for row in rows:
                writer.writerow(row)"""

    def reboot_controller_setup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Reboot Controller Setup')

        form_layout = QFormLayout()
        self.goback_x_input = QLineEdit()
        self.goback_x_input.setText(self.reboot_controller_settings['goback_x'])
        self.goback_x_input.setPlaceholderText('')
        form_layout.addRow('Goback X: ',self.goback_x_input)

        self.goback_y_input = QLineEdit()
        self.goback_y_input.setText(self.reboot_controller_settings['goback_y'])
        self.goback_y_input.setPlaceholderText('')
        form_layout.addRow('Goback Y: ',self.goback_y_input)

        self.goback_z_input = QLineEdit()
        self.goback_z_input.setText(self.reboot_controller_settings['goback_z'])
        self.goback_z_input.setPlaceholderText('')
        form_layout.addRow('Goback Z: ',self.goback_z_input)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(lambda: self.save_reboot_controller_settings(dialog))
        button_box.rejected.connect(dialog.reject)
        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()


    def save_reboot_controller_settings(self, dialog):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return

        self.reboot_controller_settings['goback_x'] = self.goback_x_input.text()
        self.reboot_controller_settings['goback_y'] = self.goback_y_input.text()
        self.reboot_controller_settings['goback_z'] = self.goback_z_input.text()

        # Verifications

        # Perform the reboot (Reset)
        move_command = self.reboot_controller_settings['goback_x']+" "+self.reboot_controller_settings['goback_y']+" "+self.reboot_controller_settings['goback_z']+" move"
        print(move_command)
        ## Move all axes to limit
        #send_command(self.ser, "-1 1 speed")
        #send_command(self.ser, "-1 2 speed")
        send_command(self.ser, "-1 3 speed")
        time.sleep(60)
        send_command(self.ser, "stopspeed")
        time.sleep(1)
        send_command(self.ser, "reset")
        time.sleep(4)
        send_command(self.ser, "-1 3 speed")
        time.sleep(2)
        send_command(self.ser, "stopspeed")
        time.sleep(2)
        send_command(self.ser, "cal")
        time.sleep(20)
        send_command(self.ser, move_command) # Ideal position may change.
        time.sleep(55) # Enough time to place the axes position
        send_command(self.ser, "2 0 setunit") # Setting the unit to (mm/s)
        time.sleep(1) # 
        send_command(self.ser, "-0.001 3 speed")
        time.sleep(1)
        send_command(self.ser, "stopspeed")
        self.update_motor_positions()
        send_command(self.ser, "-0.001 3 speed")
        time.sleep(1)
        send_command(self.ser, "stopspeed")
        self.update_motor_positions()
    
        # Close the dialog
        QMessageBox.information(self,'Controller Reboot', 'Controller Reboot done')
        dialog.accept()
        


    def serial_setup(self):
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle('Serial Port Setup')

            form_layout = QFormLayout()

            # Port Field
            ports = serial.tools.list_ports.comports()
            port_list = [port.device for port in ports]
            self.port_selector = QComboBox()
            self.port_selector.addItems(port_list)
            self.port_selector.setCurrentText(self.serial_settings.get('port', ''))
            form_layout.addRow('Port:', self.port_selector)

            # Baud Rate Selection Field
            baud_rates = ['110', '300', '600', '1200', '2400', '4800','9600','14400', '19200', '38400', '57600', '115200']
            self.baud_rate_selector = QComboBox()
            self.baud_rate_selector.addItems(baud_rates)
            self.baud_rate_selector.setCurrentText(self.serial_settings['baud_rate'])
            form_layout.addRow('Baud Rate:', self.baud_rate_selector)

            # Data Bits Selection Field
            data_bits = ['7', '8']
            self.data_bits_selector = QComboBox()
            self.data_bits_selector.addItems(data_bits)
            self.data_bits_selector.setCurrentText(self.serial_settings['data_bits'])
            form_layout.addRow('Data Bits:', self.data_bits_selector)

            # Parity Selection Field
            parity_options = ['None', 'Even', 'Odd']
            self.parity_selector = QComboBox()
            self.parity_selector.addItems(parity_options)
            self.parity_selector.setCurrentText(self.serial_settings['parity'])
            form_layout.addRow('Parity:', self.parity_selector)

            # Stop Bits Selection Field
            stop_bits = ['1', '2']
            self.stop_bits_selector = QComboBox()
            self.stop_bits_selector.addItems(stop_bits)
            self.stop_bits_selector.setCurrentText(self.serial_settings['stop_bits'])
            form_layout.addRow('Stop Bits:', self.stop_bits_selector)

            # Dialog Buttons
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(lambda: self.save_serial_settings(dialog))
            button_box.rejected.connect(dialog.reject)
            form_layout.addRow(button_box)

            dialog.setLayout(form_layout)
            dialog.exec_()
        except Exception as e:
            print(f"Error in serial_setup: {e}")
            QMessageBox.critical(self, 'Error', f'An error occurred:\n{e}')

    def save_serial_settings(self, dialog):
        # Update the serial settings with the selected values
        self.serial_settings['port'] = self.port_selector.currentText()
        self.serial_settings['baud_rate'] = self.baud_rate_selector.currentText()
        self.serial_settings['data_bits'] = self.data_bits_selector.currentText()
        self.serial_settings['parity'] = self.parity_selector.currentText()
        self.serial_settings['stop_bits'] = self.stop_bits_selector.currentText()

        #print(f"baud_rate = {int(self.serial_settings['baud_rate'])}")

        # Close the dialog
        dialog.accept()

    def create_input_box(self):
        group_box = QGroupBox('Voltage/Current Input')

        layout = QHBoxLayout()

        # Voltage and Current Radio Buttons
        self.vc_group = QButtonGroup()
        voltage_radio = QRadioButton('Voltage')
        current_radio = QRadioButton('Current')
        voltage_radio.setChecked(True)
        self.vc_group.addButton(voltage_radio)
        self.vc_group.addButton(current_radio)
        self.vc_group.buttonClicked.connect(self.update_unit_selector)

        # Value Input
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText('Value')

        # Unit Selector
        self.unit_selector = QComboBox()
        self.update_unit_selector()

        # Source On/Off Checkbox
        self.source_checkbox = QCheckBox('Source On/Off')
        self.source_checkbox.stateChanged.connect(self.confirm_source_toggle)

        # Add Widgets to Layout
        layout.addWidget(voltage_radio)
        layout.addWidget(current_radio)
        layout.addWidget(self.value_input)
        layout.addWidget(self.unit_selector)
        layout.addWidget(self.source_checkbox)

        group_box.setLayout(layout)
        return group_box

    def update_unit_selector(self):
        self.unit_selector.clear()
        if self.vc_group.checkedButton().text() == 'Voltage':
            units = ['V', 'mV', 'µV']
        else:
            units = ['A', 'mA', 'µA', 'nA', 'pA']
        self.unit_selector.addItems(units)

    def confirm_source_toggle(self, state):
        if state == Qt.Checked:
            reply = QMessageBox.question(
                self, 'Confirm Source On',
                'Are you sure you want to turn the source ON?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                self.source_checkbox.setChecked(False)
                self.source_checkbox.setCheckState(Qt.Unchecked)

    def create_joystick_box(self):
        group_box = QGroupBox('Virtual Joystick')
        layout = QGridLayout()

        # XY Control Arrows
        left_btn = QPushButton('X ←')
        up_btn = QPushButton('Y ↑')
        down_btn = QPushButton('Y ↓')
        right_btn = QPushButton('X →')
        self.xy_step_input = QLineEdit()
        self.xy_step_input.setPlaceholderText('0 um')

        left_btn.clicked.connect(self.left_btn_pressed)
        up_btn.clicked.connect(self.up_btn_pressed)
        down_btn.clicked.connect(self.down_btn_pressed)
        right_btn.clicked.connect(self.right_btn_pressed)

        # Z Control Arrows
        z_up_btn = QPushButton('Z ↑')
        z_down_btn = QPushButton('Z ↓')
        self.z_step_input = QLineEdit()
        self.z_step_input.setPlaceholderText('0 um')

        z_up_btn.clicked.connect(self.z_up_btn_pressed)
        z_down_btn.clicked.connect(self.z_down_btn_pressed)

        # Arrange Widgets
        layout.addWidget(up_btn, 0, 1)
        layout.addWidget(left_btn, 1, 0)
        layout.addWidget(self.xy_step_input, 1, 1)
        layout.addWidget(right_btn, 1, 2)
        layout.addWidget(down_btn, 2, 1)

        layout.addWidget(z_up_btn, 0, 3)
        layout.addWidget(self.z_step_input, 1, 3)
        layout.addWidget(z_down_btn, 2, 3)

        group_box.setLayout(layout)
        return group_box
    
    def left_btn_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return

        if not self.xy_step_input.text().isnumeric():
            QMessageBox.warning(self, 'Invalid Entry', 'Step size should contains only numbers.')
            return

        speed = float(self.controller_settings['pitch'])
        distance = float(self.xy_step_input.text()) / 1000 # to mm
        wait_time = distance / speed
        comd = f"-{speed} 1 speed"
        with self.write_lock:
            send_command(self.ser,comd)
        time.sleep(wait_time)
        with self.write_lock:
            send_command(self.ser,"stopspeed")
        #self.update_motor_positions()

    def right_btn_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        if not self.xy_step_input.text().isnumeric():
            QMessageBox.warning(self, 'Invalid Entry', 'Step size should contains only numbers.')
            return
        
        speed = float(self.controller_settings['pitch'])
        distance = float(self.xy_step_input.text()) / 1000 # to mm
        wait_time = distance / speed
        comd = f"{speed} 1 speed"
        with self.write_lock:
            send_command(self.ser,comd)
        time.sleep(wait_time)
        with self.write_lock:
            send_command(self.ser,"stopspeed")
        #self.update_motor_positions()

    def up_btn_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        if not self.xy_step_input.text().isnumeric():
            QMessageBox.warning(self, 'Invalid Entry', 'Step size should contains only numbers.')
            return

        
        speed = float(self.controller_settings['pitch'])
        distance = float(self.xy_step_input.text()) / 1000 # to mm
        wait_time = distance / speed
        comd = f"{speed} 2 speed"
        with self.write_lock:
            send_command(self.ser,comd)
        time.sleep(wait_time)
        with self.write_lock:
            send_command(self.ser,"stopspeed")
        #self.update_motor_positions()

    def down_btn_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        if not self.xy_step_input.text().isnumeric():
            QMessageBox.warning(self, 'Invalid Entry', 'Step size should contains only numbers.')
            return
        

        speed = float(self.controller_settings['pitch'])
        distance = float(self.xy_step_input.text()) / 1000 # to mm
        wait_time = distance / speed
        comd = f"-{speed} 2 speed"
        with self.write_lock:
            send_command(self.ser,comd)
        time.sleep(wait_time)
        with self.write_lock:
            send_command(self.ser,"stopspeed")
        #self.update_motor_positions()
    
    def z_up_btn_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        if not self.z_step_input.text().isnumeric():
            QMessageBox.warning(self, 'Invalid Entry', 'Step size should contains only numbers.')
            return
        

        speed = float(self.z_step_input.text())/ 1000
        #distance = float(self.z_step_input.text()) / 1000 # to mm
        wait_time = 1
        comd = f"-{speed} 3 speed"
        with self.write_lock:
            send_command(self.ser,comd)
        time.sleep(wait_time)
        with self.write_lock:
            send_command(self.ser,"stopspeed")
        #self.update_motor_positions()
    
    def z_down_btn_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        if not self.z_step_input.text().isnumeric():
            QMessageBox.warning(self, 'Invalid Entry', 'Step size should contains only numbers.')
            return

        speed = float(self.z_step_input.text())/1000
        #distance = float(self.z_step_input.text()) / 1000 # to mm
        wait_time = 1
        comd = f"{speed} 3 speed"
        with self.write_lock:
            send_command(self.ser,comd)
        time.sleep(wait_time)
        with self.write_lock:
            send_command(self.ser,"stopspeed")
        #self.update_motor_positions()
    


    
    def create_technique_box(self):
        group_box = QGroupBox('Technique')
        layout = QHBoxLayout()

        self.technique_selector = QComboBox()
        self.technique_selector.addItems(['Approach Scan', 'SICM','SECM', 'Chrono-Potentiometry CP', 'Chrono-Amperometry CA', 'Line Scan', 'Cyclic Voltammetry-CV', 'SECCM', 'PEIS', 'Abs SECM'])

        run_button = QPushButton('Run')
        stop_button = QPushButton('Stop')
        options_button = QPushButton('Options')
        options_button.clicked.connect(self.open_technique_options)
        run_button.clicked.connect(self.open_technique_run)
        stop_button.clicked.connect(self.open_technique_stop)

        
        layout.addWidget(self.technique_selector)
        layout.addWidget(run_button)
        layout.addWidget(stop_button)
        layout.addWidget(options_button)

        group_box.setLayout(layout)
        return group_box
    
    def open_technique_stop(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        # Have the api.StopChannel(id_, channel)
        send_command(self.ser,"stopspeed")
        self.experiment_thread.requestInterruption()

        stop = True
    
    def open_technique_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return
        
        # stop the current thread (curent_values thread) before starting a new one
        self.experiment_thread.requestInterruption() 
        technique = self.technique_selector.currentText()
        if technique == 'Approach Scan':
            self.open_approach_run()
        elif technique == 'SICM':
            self.open_sicm_run()
        elif technique == 'Line Scan':
            self.open_line_run()
        elif technique == 'Cyclic Voltammetry-CV':
            self.open_cv_run()
        elif technique == 'Chrono-Amperometry CA':
            self.open_tech_ca_run()
        elif technique == 'Chrono-Potentiometry CP':
            self.open_tech_cp_run()
        elif technique == 'SECCM':
            self.open_seccm_run()
        elif technique == 'PEIS':
            self.open_peis_run()
        elif technique == 'SECM':
            self.open_secm_run()
        elif technique == 'Abs SECM':
            self.open_abs_secm_run()


    def open_tech_cp_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_tech_cp, False)
        QMessageBox.information(self, "A measurement in progress", "CP measurement session is in progress.")


    def open_tech_ca_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_tech_ca, False)
        QMessageBox.information(self, "A measurement in progress", "CA measurement session is in progress.")
        
    def open_cv_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_cv, False)
        QMessageBox.information(self, "A measurement in progress", "CV measurement session is in progress.")

    def open_ca_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_ca, False)
        QMessageBox.information(self, "A measurement in progress", "CA measurement session is in progress.")

    def open_line_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_line_scan, False)
        QMessageBox.information(self, "A measurement in progress", "Line Scan measurement session is in progress.")

    def open_abs_secm_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.abs_secm_options['current_pos'] = f"{self.x_input.text()},{self.y_input.text()},{self.z_input.text()}"
        self.start_experiment(perf_abs_secm, False)
        QMessageBox.information(self, "A measurement in progress", "Abs SECM measurement session is in progress.")

    def open_secm_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_secm, False)
        QMessageBox.information(self, "A measurement in progress", "SECM measurement session is in progress.")

    def open_sicm_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_sicm, False)
        QMessageBox.information(self, "A measurement in progress", "SICM measurement session is in progress.")

    def open_peis_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_peis, False)
        QMessageBox.information(self, "A measurement in progress", "PEIS measurement session is in progress.")

    def open_approach_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        self.start_experiment(perf_ca, False)
        QMessageBox.information(self, "A measurement in progress", "A measurement session is in progress.")
        #print(f"\n\n thread = {self.experiment_thread.isInterruptionRequested()}")


        

    def open_seccm_run(self):
        if not self.potentiostat_connected:
            QMessageBox.warning(self, 'Potentiostat Not Connected', 'Please connect the potentiostat first.')
            return

        number_of_steps = int(self.seccm_options['points_number'].split('x')[0].strip())
        #print(f"number of steps {number_of_steps}")
        self.number_of_steps = number_of_steps
        self.i = 1
        self.j = 1
        x_move_r = self.seccm_options['x_width']+" 1 speed"
        x_move_l = "-"+self.seccm_options['x_width']+" 1 speed"
        y_move = "-"+self.seccm_options['y_length']+" 2 speed"
        self.x_move_r = x_move_r 
        self.x_move_l = x_move_l 
        self.y_move = y_move 
        right = True
        self.right = right
        # TODO: perform Approach if not in contact with the surface.
        self.first = True
        self.retract_values_file = open("retract_values_file.csv", "w")
        self.seccm_positions_file = open("seccm_positions_file.csv", "w")
        self.start_experiment(perf_seccm, True)
        
        #while self.experiment_thread._is_running:
        #    time.sleep(0.001)
        ## Get the position of all axes 
        ## CV datadump, writing in all the positions and their cv in a same file.
        #self.seccm_datadump = open("self.seccm_datadump.csv", "w")
        ## write the first position coordinates
        #send_command(self.ser, "pos")
        #x_pos, y_pos, z_pos = extract_coordinates(read_response(self.ser))
        #self.seccm_datadump.write(f"x: {x_pos:.4f}, y: {y_pos:.4f}, z:{z_pos:.4f}\n")
        #self.seccm_datadump.write("t (s),Ewe (V),I (A),Cycle (N)\n")
        ## perform the first CV
        #self.start_experiment(perf_cv)
        # In Contact, so do a CV
        # Get the tip up (specific distance from the surface)
        # The next point by : Moving x or y
        # Perform an approach 
        # End loop



    def open_technique_options(self):
        technique = self.technique_selector.currentText()
        if technique == 'Approach Scan':
            self.open_approach_options()
        elif technique == 'SICM':
            self.open_sicm_options()
        elif technique == 'Line Scan':
            self.open_line_options()
        elif technique == 'Cyclic Voltammetry-CV':
            self.open_cv_options()
        elif technique == 'Chrono-Amperometry CA':
            self.open_tech_ca_options()
        elif technique == 'Chrono-Potentiometry CP':
            self.open_tech_cp_options()
        elif technique == 'SECCM':
            self.open_seccm_options()
        elif technique == 'PEIS':
            self.open_peis_options()
        elif technique == 'SECM':
            self.open_secm_options()
        elif technique == 'Abs SECM':
            self.open_abs_secm_options()

    
    def open_tech_cp_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('CP Options')

        form_layout = QFormLayout()
        bool_choices = ['True','False']
        # vs_init
        self.tech_cp_vs_init_select = QComboBox()
        self.tech_cp_vs_init_select.addItems(bool_choices)
        self.tech_cp_vs_init_select.setCurrentText(self.cp_options['vs_init'])
        form_layout.addRow('vs_init:', self.tech_cp_vs_init_select)

        # voltage applied
        self.tech_cp_current_input = QLineEdit()
        if isinstance(self.cp_options['current_applied'], list):
            self.tech_cp_current_input.setText(' '.join(self.cp_options['current_applied']))
        else:
            self.tech_cp_current_input.setText(self.cp_options['current_applied'])
        form_layout.addRow('current step (A) :', self.tech_cp_current_input)

        # Duration 
        self.tech_cp_duration_input = QLineEdit()
        if isinstance(self.cp_options['duration'], list):
            self.tech_cp_duration_input.setText(' '.join(self.cp_options['duration']))
        else:
            self.tech_cp_duration_input.setText(self.cp_options['duration'])
        form_layout.addRow('Duration step (s) :', self.tech_cp_duration_input)

        # Record dT
        self.tech_cp_record_dt_input = QLineEdit()
        self.tech_cp_record_dt_input.setText(self.cp_options['record_dT'])
        form_layout.addRow('Record_dT :', self.tech_cp_record_dt_input)

        # Record dI
        self.tech_cp_record_dE_input = QLineEdit()
        self.tech_cp_record_dE_input.setText(self.cp_options['record_dE'])
        form_layout.addRow('Record_dE :', self.tech_cp_record_dE_input)

        # N_Cycles
        self.tech_cp_n_cycles_input = QLineEdit()
        self.tech_cp_n_cycles_input.setText(self.cp_options['N_Cycles'])
        form_layout.addRow('N_Cycles :', self.tech_cp_n_cycles_input)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_tech_cp_options(dialog))
        button_box.rejected.connect(dialog.reject)

        # Connect Save and Open buttons
        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_tech_cp_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_tech_cp_options_from_file)

        form_layout.addRow(button_box)


        dialog.setLayout(form_layout)
        dialog.exec_()

    
    def save_tech_cp_options_to_file(self):
        base_file, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save CP Options and Results (enter base file name)",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        if base_file:
            # Générer deux noms de fichiers en ajoutant les suffixes selon l'extension choisie.
            if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                base = base_file.replace(".json", "")
                options_file = base + "_options.json"
                results_file = base + "_results.json"
            elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                base = base_file.replace(".csv", "")
                options_file = base + "_options.csv"
                results_file = base + "_results.csv"
            else:
                options_file = base_file + "_options.json"
                results_file = base_file + "_results.json"

            try:
                # Récupération des options
                options = {
                    'vs_init': self.tech_cp_vs_init_select.currentText(),
                    'current_applied': self.tech_cp_current_input.text(),
                    'duration': self.tech_cp_duration_input.text(),
                    'record_dT': self.tech_cp_record_dt_input.text(),
                    'record_dE': self.tech_cp_record_dE_input.text(),
                    'N_Cycles': self.tech_cp_n_cycles_input.text(),
                }

                # Récupération des résultats provenant du fichier 'electro_cp.csv'
                results = []
                try:
                    with open('electro_cp.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    raise Exception(f"Failed to read 'electro_cp.csv': {read_error}")

                # Enregistrement selon le format choisi
                if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"CP options saved to:\n{options_file}\nCP results saved to:\n{results_file}"
                elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                    with open(options_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Ligne vide pour séparer.
                    with open(results_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        if results:
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_cp.csv"])
                    message = f"CP options saved to:\n{options_file}\nCP results saved to:\n{results_file}"
                else:
                    # Fallback sur JSON
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"CP options saved to:\n{options_file}\nCP results saved to:\n{results_file}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")

        
    def save_tech_cp_options(self, dialog):
        # Save the values
        self.cp_options['vs_init'] = self.tech_cp_vs_init_select.currentText()
        self.cp_options['current_applied'] = self.tech_cp_current_input.text()
        self.cp_options['duration'] = self.tech_cp_duration_input.text()
        self.cp_options['record_dT'] = self.tech_cp_record_dt_input.text()
        self.cp_options['record_dE'] = self.tech_cp_record_dE_input.text()
        self.cp_options['N_Cycles'] = self.tech_cp_n_cycles_input.text()

        # You can add validation here if needed
        # check if the current input contains " "
        if " " in self.cp_options['current_applied']:
            # multiple current steps create a list of current steps by splitting by " "
            self.cp_options['current_applied'] = self.cp_options['current_applied'].split(' ')

            # check if the duration input contains " "
            if " " in self.cp_options['duration']:
                # multiple duration steps create a list of duration steps by splitting by " "
                self.cp_options['duration'] = self.cp_options['duration'].split(' ')
                if len(self.cp_options['current_applied']) != len(self.cp_options['duration']):
                    QMessageBox.critical(self, "Error", "The number of current steps should be equal to the number of duration steps.")
                    return
        else:
            self.cp_options['current_applied'] = []
            self.cp_options['current_applied'].append(self.tech_cp_current_input.text())
            
        
        print(self.cp_options['current_applied'])


        dialog.accept()

    def upload_tech_cp_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open CP Options", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as file:
                    data = json.load(file)

                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain CP options.")
                    return
                
                data = options
                self.ca_options.update(data)
                # Update UI fields
                self.tech_cp_vs_init_select.setCurrentText(data['vs_init'])
                self.tech_cp_current_input.setText(data['current_applied'])
                self.tech_cp_duration_input.setText(data['duration'])
                self.tech_cp_record_dt_input.setText(data['record_dT'])
                self.tech_cp_record_dE_input.setText(data['record_dE'])
                self.tech_cp_n_cycles_input.setText(data['N_Cycles'])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load options: {e}")


    # tech CA options

    def open_tech_ca_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('CA Options')

        form_layout = QFormLayout()
        bool_choices = ['True','False']
        # vs_init
        self.tech_ca_vs_init_select = QComboBox()
        self.tech_ca_vs_init_select.addItems(bool_choices)
        self.tech_ca_vs_init_select.setCurrentText(self.ca_options['vs_init'])
        form_layout.addRow('vs_init:', self.tech_ca_vs_init_select)

        # voltage applied
        self.tech_ca_voltage_input = QLineEdit()
        if isinstance(self.ca_options['voltage_applied'], list):
            self.tech_ca_voltage_input.setText(' '.join(self.ca_options['voltage_applied']))
        else: 
            self.tech_ca_voltage_input.setText(self.ca_options['voltage_applied'])
        form_layout.addRow('voltage step (V) :', self.tech_ca_voltage_input)

        # Duration 
        self.tech_ca_duration_input = QLineEdit()
        if isinstance(self.ca_options['duration'], list):
            self.tech_ca_duration_input.setText(' '.join(self.ca_options['duration']))
        else:
            self.tech_ca_duration_input.setText(self.ca_options['duration'])
        form_layout.addRow('Duration step (s) :', self.tech_ca_duration_input)

        # Record dT
        self.tech_ca_record_dt_input = QLineEdit()
        self.tech_ca_record_dt_input.setText(self.ca_options['record_dT'])
        form_layout.addRow('Record_dT :', self.tech_ca_record_dt_input)

        # Record dI
        self.tech_ca_record_dI_input = QLineEdit()
        self.tech_ca_record_dI_input.setText(self.ca_options['record_dI'])
        form_layout.addRow('Record_dI :', self.tech_ca_record_dI_input)

        # N_Cycles
        self.tech_ca_n_cycles_input = QLineEdit()
        self.tech_ca_n_cycles_input.setText(self.ca_options['N_Cycles'])
        form_layout.addRow('N_Cycles :', self.tech_ca_n_cycles_input)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_tech_ca_options(dialog))
        button_box.rejected.connect(dialog.reject)

        # Connect Save and Open buttons
        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_tech_ca_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_tech_ca_options_from_file)

        form_layout.addRow(button_box)


        dialog.setLayout(form_layout)
        dialog.exec_()

    
    def save_tech_cp_options_to_file(self):
        base_file, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save CP Options and Results (enter base file name)",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        if base_file:
            # Générer deux noms de fichiers en ajoutant les suffixes selon l'extension choisie.
            if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                base = base_file.replace(".json", "")
                options_file = base + "_options.json"
                results_file = base + "_results.json"
            elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                base = base_file.replace(".csv", "")
                options_file = base + "_options.csv"
                results_file = base + "_results.csv"
            else:
                options_file = base_file + "_options.json"
                results_file = base_file + "_results.json"

            try:
                # Récupération des options
                options = {
                    'vs_init': self.tech_cp_vs_init_select.currentText(),
                    'current_applied': self.tech_cp_current_input.text(),
                    'duration': self.tech_cp_duration_input.text(),
                    'record_dT': self.tech_cp_record_dt_input.text(),
                    'record_dE': self.tech_cp_record_dE_input.text(),
                    'N_Cycles': self.tech_cp_n_cycles_input.text(),
                }

                # Récupération des résultats provenant du fichier 'electro_cp.csv'
                results = []
                try:
                    with open('electro_cp.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    raise Exception(f"Failed to read 'electro_cp.csv': {read_error}")

                # Enregistrement selon le format choisi
                if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"CP options saved to:\n{options_file}\nCP results saved to:\n{results_file}"
                elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                    with open(options_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Ligne vide pour séparer.
                    with open(results_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        if results:
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_cp.csv"])
                    message = f"CP options saved to:\n{options_file}\nCP results saved to:\n{results_file}"
                else:
                    # Fallback sur JSON
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"CP options saved to:\n{options_file}\nCP results saved to:\n{results_file}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")


    def save_tech_ca_options(self, dialog):
        # Save the values
        self.ca_options['vs_init'] = self.tech_ca_vs_init_select.currentText()
        self.ca_options['voltage_applied'] = self.tech_ca_voltage_input.text()
        self.ca_options['duration'] = self.tech_ca_duration_input.text()
        self.ca_options['record_dT'] = self.tech_ca_record_dt_input.text()
        self.ca_options['record_dI'] = self.tech_ca_record_dI_input.text()
        self.ca_options['N_Cycles'] = self.tech_ca_n_cycles_input.text()

        # You can add validation here if needed
        # check if the voltage input contains " "
        if " " in self.ca_options['voltage_applied']:
            # multipe voltage steps create a list of volatge steps by splitting by " "
            self.ca_options['voltage_applied'] = self.ca_options['voltage_applied'].split(' ')
            print("more")
            

            # check if the duration input contains " "
            if " " in self.ca_options['duration']:
                # multiple duration steps create a list of duration steps by splitting by " "
                self.ca_options['duration'] = self.ca_options['duration'].split(' ')
                if len(self.ca_options['voltage_applied']) != len(self.ca_options['duration']):
                    QMessageBox.critical(self, "Error", "The number of voltage steps should be equal to the number of duration steps.")
                    return
        else:
            self.ca_options['voltage_applied'] = []
            self.ca_options['voltage_applied'].append(self.tech_ca_voltage_input.text())
            

        #self.ca_options['voltage_applied'] = float(self.ca_options['voltage_applied'])
        print(self.ca_options['voltage_applied'])



        dialog.accept()


    def upload_tech_ca_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open CA Options", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as file:
                    data = json.load(file)

                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain CA options.")
                    return
                
                data = options
                self.ca_options.update(data)
                # Update UI fields
                self.tech_ca_vs_init_select.setCurrentText(data['vs_init'])
                self.tech_ca_voltage_input.setText(data['voltage_applied'])
                self.tech_ca_duration_input.setText(data['duration'])
                self.tech_ca_record_dt_input.setText(data['record_dT'])
                self.tech_ca_record_dI_input.setText(data['record_dI'])
                self.tech_ca_n_cycles_input.setText(data['N_Cycles'])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load options: {e}")



    def open_abs_secm_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Abs SECM Options')

        form_layout = QFormLayout()


        # Voltage Applied Input Field
        self.abs_secm_voltage_input = QLineEdit()
        self.abs_secm_voltage_input.setText(self.abs_secm_options['voltage'])
        form_layout.addRow('Voltage Applied (V):', self.abs_secm_voltage_input)

        # Estimated Approach Time Input Field
        self.abs_secm_aproximate_time_input = QLineEdit()
        self.abs_secm_aproximate_time_input.setText(self.abs_secm_options['aproximate_time'])
        form_layout.addRow('Estimated Approach Time (s):', self.abs_secm_aproximate_time_input)

        # Retracting height
        self.abs_secm_distance_input = QLineEdit()
        self.abs_secm_distance_input.setText(self.abs_secm_options['distance'])
        form_layout.addRow('Retracting height (mm):', self.abs_secm_distance_input)

        # Retracting speed
        self.abs_secm_z_speed_input = QLineEdit()
        self.abs_secm_z_speed_input.setText(self.abs_secm_options['z_speed'])
        form_layout.addRow('Retracting speed (mm/s):', self.abs_secm_z_speed_input)

        # Spike Threshold Input Field
        self.abs_secm_nb_rounds_input = QLineEdit()
        self.abs_secm_nb_rounds_input.setText(self.abs_secm_options['nb_rounds'])
        form_layout.addRow('Nb rounds (1 = B -> A -> B) :', self.abs_secm_nb_rounds_input)

        # Dialog Buttons # Open to upload from file
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)

        button_box.accepted.connect(lambda: self.save_abs_secm_options(dialog))
        button_box.rejected.connect(dialog.reject)

        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_abs_secm_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_abs_secm_options_from_file)
        
        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_abs_secm_options_to_file(self):
        base_file, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Abs SECM Options and Results (enter base file name)",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        if base_file:
            # Générer deux noms de fichiers en ajoutant les suffixes selon l'extension choisie.
            if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                base = base_file.replace(".json", "")
                options_file = base + "_options.json"
                results_file = base + "_results.json"
            elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                base = base_file.replace(".csv", "")
                options_file = base + "_options.csv"
                results_file = base + "_results.csv"
            else:
                options_file = base_file + "_options.json"
                results_file = base_file + "_results.json"

            try:
                # Récupération des options
                options = {
                    'voltage': self.abs_secm_voltage_input.text(),
                    'aproximate_time': self.abs_secm_aproximate_time_input.text(),
                    'distance': self.abs_secm_distance_input.text(),
                    'z_speed': self.abs_secm_z_speed_input.text(),
                    'nb_rounds':  self.abs_secm_nb_rounds_input.text(),
                }

                # Récupération des résultats provenant du fichier 'electro_abs_secm_pos.csv'
                results = []
                try:
                    with open('electro_abs_secm_pos.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    raise Exception(f"Failed to read 'electro_abs_secm_pos.csv': {read_error}")

                # Enregistrement selon le format choisi
                if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"Abs SECM options saved to:\n{options_file}\nAbs SECM results saved to:\n{results_file}"
                elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                    with open(options_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                    with open(results_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        if results:
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_abs_secm_pos.csv"])
                    message = f"Abs SECM options saved to:\n{options_file}\nAbs SECM results saved to:\n{results_file}"
                else:
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"Abs SECM options saved to:\n{options_file}\nAbs SECM results saved to:\n{results_file}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")

    def upload_abs_secm_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open abs_secm Options", "", "JSON Files (*.json)")
        if file_name:
            try: 
                with open(file_name, 'r') as file:
                    data = json.load(file)
                
                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain abs_secm options.")
                    return
                
                data = options
                self.abs_secm_options.update(data)

                # update UI fields
                self.abs_secm_voltage_input.setText(data['voltage'])
                self.abs_secm_aproximate_time_input.setText(data['aproximate_time'])
                self.abs_secm_distance_input.setText(data['distance'])
                self.abs_secm_z_speed_input.setText(data['z_speed'])
                self.abs_secm_nb_rounds_input.setText(data['nb_rounds'])

                #QMessageBox.information(self, "Open Options", "abs_secm options are successfully loaded.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failled to load options : {e}")
        

    def save_abs_secm_options(self, dialog):
        # Save the values
        self.abs_secm_options['voltage'] = self.abs_secm_voltage_input.text()
        self.abs_secm_options['aproximate_time'] = self.abs_secm_aproximate_time_input.text()
        self.abs_secm_options['distance'] = self.abs_secm_distance_input.text()
        self.abs_secm_options['z_speed'] = self.abs_secm_z_speed_input.text()
        self.abs_secm_options['nb_rounds'] = self.abs_secm_nb_rounds_input.text()
        

        # You can add validation here if needed
        dialog.accept()

    def open_secm_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('SECM Options')

        form_layout = QFormLayout()

        # z_speed Speed Input Field
        self.secm_z_speed_input = QLineEdit()
        self.secm_z_speed_input.setText(self.secm_options['z_speed'])
        form_layout.addRow('z speed (mm/s):', self.secm_z_speed_input)

        # Voltage Applied Input Field
        self.secm_voltage_input = QLineEdit()
        self.secm_voltage_input.setText(self.secm_options['voltage'])
        form_layout.addRow('Voltage Applied (V):', self.secm_voltage_input)

        # Estimated Approach Time Input Field
        self.secm_aproximate_time_input = QLineEdit()
        self.secm_aproximate_time_input.setText(self.secm_options['aproximate_time'])
        form_layout.addRow('Estimated Approach Time (s):', self.secm_aproximate_time_input)

        # Spike Threshold Input Field
        self.secm_stop_point_input = QLineEdit()
        self.secm_stop_point_input.setText(self.secm_options['stop_point'])
        form_layout.addRow('Stop point :', self.secm_stop_point_input)

        # Spike Threshold Input Field
        self.secm_skip_input = QLineEdit()
        self.secm_skip_input.setText(self.secm_options['skip'])
        form_layout.addRow('Stop point :', self.secm_skip_input)

        # Dialog Buttons # Open to upload from file
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)

        button_box.accepted.connect(lambda: self.save_secm_options(dialog))
        button_box.rejected.connect(dialog.reject)

        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_secm_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_secm_options_from_file)
        
        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_secm_options_to_file(self):
        base_file, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save SECM Options and Results (enter base file name)",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        if base_file:
            # Générer deux noms de fichiers en ajoutant les suffixes selon l'extension choisie.
            if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                base = base_file.replace(".json", "")
                options_file = base + "_options.json"
                results_file = base + "_results.json"
            elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                base = base_file.replace(".csv", "")
                options_file = base + "_options.csv"
                results_file = base + "_results.csv"
            else:
                options_file = base_file + "_options.json"
                results_file = base_file + "_results.json"

            try:
                # Récupération des options
                options = {
                    'z_speed': self.secm_z_speed_input.text(),
                    'voltage': self.secm_voltage_input.text(),
                    'aproximate_time': self.secm_aproximate_time_input.text(),
                    'stop_point': self.secm_stop_point_input.text(),
                    'skip': self.secm_skip_input.text(),
                }

                # Récupération des résultats provenant du fichier 'electro_secm_pos.csv'
                results = []
                try:
                    with open('electro_secm_pos.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    raise Exception(f"Failed to read 'electro_secm_pos.csv': {read_error}")

                # Enregistrement selon le format choisi
                if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"SECM options saved to:\n{options_file}\nSECM results saved to:\n{results_file}"
                elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                    with open(options_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                    with open(results_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        if results:
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_secm_pos.csv"])
                    message = f"SECM options saved to:\n{options_file}\nSECM results saved to:\n{results_file}"
                else:
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"SECM options saved to:\n{options_file}\nSECM results saved to:\n{results_file}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")

    def upload_secm_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open SECM Options", "", "JSON Files (*.json)")
        if file_name:
            try: 
                with open(file_name, 'r') as file:
                    data = json.load(file)
                
                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain SECM options.")
                    return
                
                data = options
                self.secm_options.update(data)

                # update UI fields
                self.secm_z_speed_input.setText(data['z_speed'])
                self.secm_voltage_input.setText(data['voltage'])
                self.secm_aproximate_time_input.setText(data['aproximate_time'])
                self.secm_stop_point_input.setText(data['stop_point'])
                self.secm_skip_input.setText(data['skip'])

                #QMessageBox.information(self, "Open Options", "SECM options are successfully loaded.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failled to load options : {e}")
        

    def save_secm_options(self, dialog):
        # Save the values
        self.secm_options['z_speed'] = self.secm_z_speed_input.text()
        self.secm_options['voltage'] = self.secm_voltage_input.text()
        self.secm_options['aproximate_time'] = self.secm_aproximate_time_input.text()
        self.secm_options['stop_point'] = self.secm_stop_point_input.text()
        self.secm_options['skip'] = self.secm_skip_input.text()

        # You can add validation here if needed
        dialog.accept()
    


    def open_sicm_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('SICM Options')

        form_layout = QFormLayout()

        # z_speed Speed Input Field
        self.sicm_z_speed_input = QLineEdit()
        self.sicm_z_speed_input.setText(self.sicm_options['z_speed'])
        form_layout.addRow('z speed (mm/s):', self.sicm_z_speed_input)

        # Voltage Applied Input Field
        self.sicm_voltage_input = QLineEdit()
        self.sicm_voltage_input.setText(self.sicm_options['voltage'])
        form_layout.addRow('Voltage Applied (V):', self.sicm_voltage_input)

        # Estimated Approach Time Input Field
        self.sicm_aproximate_time_input = QLineEdit()
        self.sicm_aproximate_time_input.setText(self.sicm_options['aproximate_time'])
        form_layout.addRow('Estimated Approach Time (s):', self.sicm_aproximate_time_input)

        # Spike Threshold Input Field
        self.sicm_stop_point_input = QLineEdit()
        self.sicm_stop_point_input.setText(self.sicm_options['stop_point'])
        form_layout.addRow('Stop point :', self.sicm_stop_point_input)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_sicm_options(dialog))
        button_box.rejected.connect(dialog.reject)

        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_sicm_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_sicm_options_from_file)
        
        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_sicm_options_to_file(self):
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save CP Options and Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)")
        if file_name:
            try:
                # Gather options
                options = {
                    'z_speed': self.sicm_z_speed_input.text(),
                    'voltage': self.sicm_voltage_input.text(),
                    'aproximate_time': self.sicm_aproximate_time_input.text(),
                    'stop_point': self.sicm_stop_point_input.text(),
                }

                # Gather results
                """results = {
                    'Time (s)': self.sicm_time,
                    'Ewe (V)': self.sicm_Ewe,
                    'Iwe (A)': self.sicm_Iwe,
                    'Cycle (N)': self.sicm_cycle,
                }"""
                results = []
                try:
                    with open('electro_sicm_out.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    # If reading fails, you can decide whether to continue or show an error.
                    raise Exception(f"Failed to read 'electro_sicm_out.csv': {read_error}")

                # Combine options and results
                data_to_save = {
                    'options': options,
                    'results': results,
                }

                # Determine format based on the selected filter or file extension
                if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                    # Save data as JSON
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"SICM options and results saved successfully in JSON format.\n{file_name}"
                elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                    # Save data as CSV
                    # we write a two-part CSV file:
                    # 1. The options section as key/value pairs.
                    # 2. A blank row, then the results (read from electro_cp.csv).
                    with open(file_name, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        # Write options.
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Empty row for separation.

                        # Write results.
                        if results:
                            # Write header row using keys from the first results row.
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            # Write each row of results.
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_sicm_out.csv"])

                    message = f"SICM options and results saved successfully in CSV format.\n{file_name}"
                else:
                    # Fallback to JSON if no valid filter is detected.
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"SICM options and results saved successfully in JSON format.\n{file_name}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")

    def upload_sicm_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open SICM Options", "", "JSON Files (*.json)")
        if file_name:
            try: 
                with open(file_name, 'r') as file:
                    data = json.load(file)


                # Update options only 
                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain SICM options.")
                    return
                
                data = options
                self.sicm_options.update(data)

                # update UI fields
                self.sicm_z_speed_input.setText(data['z_speed'])
                self.sicm_voltage_input.setText(data['voltage'])
                self.sicm_aproximate_time_input.setText(data['aproximate_time'])
                self.sicm_stop_point_input.setText(data['stop_point'])

                #QMessageBox.information(self, "Open Options", "SICM options are successfully loaded.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failled to load options : {e}")

        



    def save_sicm_options(self, dialog):
        # Save the values
        self.sicm_options['z_speed'] = self.sicm_z_speed_input.text()
        self.sicm_options['voltage'] = self.sicm_voltage_input.text()
        self.sicm_options['aproximate_time'] = self.sicm_aproximate_time_input.text()
        self.sicm_options['stop_point'] = self.sicm_stop_point_input.text()

        # You can add validation here if needed
        dialog.accept()

    def open_peis_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('PEIS Options')

        form_layout = QFormLayout()
        
        bool_choices = ['True','False']
        # vs_init
        self.peis_vs_init_select = QComboBox()
        self.peis_vs_init_select.addItems(bool_choices)
        self.peis_vs_init_select.setCurrentText(self.peis_options['vs_init'])
        form_layout.addRow('vs_init:', self.peis_vs_init_select)

        # init voltage step
        self.peis_init_volt_step_input = QLineEdit()
        self.peis_init_volt_step_input.setText(self.peis_options['init_voltage_step'])
        form_layout.addRow('Initial voltage step (V) :', self.peis_init_volt_step_input)

        # duration step input
        self.peis_duration_step_input = QLineEdit()
        self.peis_duration_step_input.setText(self.peis_options['duration_step'])
        form_layout.addRow('Step duration (s) :', self.peis_duration_step_input)

        # recorr dt input
        self.peis_record_dt_input = QLineEdit()
        self.peis_record_dt_input.setText(self.peis_options['record_dt'])
        form_layout.addRow('Record every dt (s) :', self.peis_record_dt_input)

        # record dI input
        self.peis_record_dI_input = QLineEdit()
        self.peis_record_dI_input.setText(self.peis_options['record_dI'])
        form_layout.addRow('Record every dI (A) :', self.peis_record_dI_input)

        # final freq input
        self.peis_final_freq_input = QLineEdit()
        self.peis_final_freq_input.setText(self.peis_options['final_freq'])
        form_layout.addRow('Final frequency (Hz) :', self.peis_final_freq_input)

        # initial freq input
        self.peis_initial_freq_input = QLineEdit()
        self.peis_initial_freq_input.setText(self.peis_options['initial_freq'])
        form_layout.addRow('Initial frequency (Hz) :', self.peis_initial_freq_input)

        # sweep selector
        self.peis_sweep_select = QComboBox()
        self.peis_sweep_select.addItems(bool_choices)
        self.peis_sweep_select.setCurrentText(self.peis_options['sweep'])
        form_layout.addRow('sweep linear/logarithmic\n(TRUE for linear points spacing):', self.peis_sweep_select)

        # amplitude voltage input
        self.peis_amplitude_voltage_input = QLineEdit()
        self.peis_amplitude_voltage_input.setText(self.peis_options['amplitude_voltage'])
        form_layout.addRow('Sine amplitude (V) :', self.peis_amplitude_voltage_input)

        # freq number input
        self.peis_freq_number_input = QLineEdit()
        self.peis_freq_number_input.setText(self.peis_options['freq_number'])
        form_layout.addRow('Number of frequencies :', self.peis_freq_number_input)

        # avg_n input
        self.peis_avg_n_input = QLineEdit()
        self.peis_avg_n_input.setText(self.peis_options['avg_n'])
        form_layout.addRow('Number of repeat times\n(used for frequencies averaging) :', self.peis_avg_n_input)

        # correction
        self.peis_correction_select = QComboBox()
        self.peis_correction_select.addItems(bool_choices)
        self.peis_correction_select.setCurrentText(self.peis_options['correction'])
        form_layout.addRow('Non-stationary correction :', self.peis_correction_select)

        # wait steady input
        self.peis_wait_steady_input = QLineEdit()
        self.peis_wait_steady_input.setText(self.peis_options['wait_steady'])
        form_layout.addRow('Number of period to wait\nbefore each frequency :', self.peis_wait_steady_input)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_peis_options(dialog))
        button_box.rejected.connect(dialog.reject)

        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_peis_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_peis_options_from_file)
        
        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_peis_options_to_file(self):
        base_file, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save PEIS Options and Results (enter base file name)",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)"
        )
        if base_file:
            # Générer deux noms de fichiers en ajoutant les suffixes selon l'extension choisie.
            if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                base = base_file.replace(".json", "")
                options_file = base + "_options.json"
                results_file = base + "_results.json"
            elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                base = base_file.replace(".csv", "")
                options_file = base + "_options.csv"
                results_file = base + "_results.csv"
            else:
                options_file = base_file + "_options.json"
                results_file = base_file + "_results.json"

            try:
                # Récupération des options
                options = {
                    'vs_init': self.peis_vs_init_select.currentText(),
                    'init_voltage_step': self.peis_init_volt_step_input.text(),
                    'duration_step': self.peis_duration_step_input.text(),
                    'record_dt': self.peis_record_dt_input.text(),
                    'record_dI': self.peis_record_dI_input.text(),
                    'final_freq': self.peis_final_freq_input.text(),
                    'initial_freq': self.peis_initial_freq_input.text(),
                    'sweep': self.peis_sweep_select.currentText(),
                    'amplitude_voltage': self.peis_amplitude_voltage_input.text(),
                    'freq_number': self.peis_freq_number_input.text(),
                    'avg_n': self.peis_avg_n_input.text(),
                    'correction': self.peis_correction_select.currentText(),
                    'wait_steady': self.peis_wait_steady_input.text(),
                }

                # Récupération des résultats provenant du fichier 'seccm_peis_p2.csv'
                results = []
                try:
                    with open('seccm_peis_p2.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    raise Exception(f"Failed to read 'seccm_peis_p2.csv': {read_error}")

                # Enregistrement selon le format choisi
                if selected_filter.startswith("JSON") or base_file.endswith(".json"):
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"PEIS options saved to:\n{options_file}\nPEIS results saved to:\n{results_file}"
                elif selected_filter.startswith("CSV") or base_file.endswith(".csv"):
                    with open(options_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                    with open(results_file, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)
                        if results:
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in seccm_peis_p2.csv"])
                    message = f"PEIS options saved to:\n{options_file}\nPEIS results saved to:\n{results_file}"
                else:
                    # Fallback sur JSON
                    with open(options_file, 'w') as file:
                        json.dump(options, file, indent=4)
                    with open(results_file, 'w') as file:
                        json.dump(results, file, indent=4)
                    message = f"PEIS options saved to:\n{options_file}\nPEIS results saved to:\n{results_file}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")

    def upload_peis_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open PEIS Options", "", "JSON Files (*.json)")
        if file_name:
            try: 
                with open(file_name, 'r') as file:
                    data = json.load(file)
                
                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain TechniqueName options.")
                    return
                data = options
                #self.sicm_options.update(data)

                # update UI fields
                self.peis_vs_init_select.setCurrentText(data['vs_init'])
                self.peis_init_volt_step_input.setText(data['init_voltage_step'])
                self.peis_duration_step_input.setText(data['duration_step'])
                self.peis_record_dt_input.setText(data['record_dt'])
                self.peis_record_dI_input.setText(data['record_dI'])
                self.peis_final_freq_input.setText(data['final_freq'])
                self.peis_initial_freq_input.setText(data['initial_freq'])
                self.peis_sweep_select.setCurrentText(data['sweep'])
                self.peis_amplitude_voltage_input.setText(data['amplitude_voltage'])
                self.peis_freq_number_input.setText(data['freq_number'])
                self.peis_avg_n_input.setText(data['avg_n'])
                self.peis_correction_select.setCurrentText(data['correction'])
                self.peis_wait_steady_input.setText(data['wait_steady'])

                #QMessageBox.information(self, "Open Options", "PEIS options are successfully loaded.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failled to load options : {e}")


    def save_peis_options(self, dialog):
        self.peis_options['vs_init'] = self.peis_vs_init_select.currentText()
        self.peis_options['init_voltage_step'] = self.peis_init_volt_step_input.text()
        self.peis_options['duration_step'] = self.peis_duration_step_input.text()
        self.peis_options['record_dt'] = self.peis_record_dt_input.text()
        self.peis_options['record_dI'] = self.peis_record_dI_input.text()
        self.peis_options['final_freq'] = self.peis_final_freq_input.text()
        self.peis_options['initial_freq'] = self.peis_initial_freq_input.text()
        self.peis_options['sweep'] = self.peis_sweep_select.currentText()
        self.peis_options['amplitude_voltage'] = self.peis_amplitude_voltage_input.text()
        self.peis_options['freq_number'] = self.peis_freq_number_input.text()
        self.peis_options['avg_n'] = self.peis_avg_n_input.text()
        self.peis_options['correction'] = self.peis_correction_select.currentText()
        self.peis_options['wait_steady'] = self.peis_wait_steady_input.text()

        #print(f"vs_int = {bool(self.peis_options['vs_init'])}")


        # You can add validation here if needed
        dialog.accept()

    def open_seccm_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('SECCM Options')

        form_layout = QFormLayout()

        # Points number selector
        list_points = ['3x3', '5x5', '7x7', '8x8', '9x9', '10x10', '11x11']
        self.seccm_points_num_selector = QComboBox()
        self.seccm_points_num_selector.addItems(list_points)
        self.seccm_points_num_selector.setCurrentText(self.seccm_options['points_number'])
        form_layout.addRow('Select points disposition', self.seccm_points_num_selector)

        # Technique measured  selector
        #list_points = ['CV', 'PEIS']
        self.seccm_tech_measure_input = QLineEdit()
        #self.seccm_tech_measure_input.addItems(list_points)
        tech_measure_str = ','.join(self.seccm_options['tech_measure'])
        self.seccm_tech_measure_input.setText(tech_measure_str)
        #self.seccm_tech_measure_input.setText(self.seccm_options['tech_measure'])
        form_layout.addRow('Add technique (eg: CV, CA)', self.seccm_tech_measure_input)

        # X width input field
        self.seccm_x_width_input = QLineEdit()
        self.seccm_x_width_input.setText(self.seccm_options['x_width'])
        form_layout.addRow('x_width (mm):', self.seccm_x_width_input)

        # Y length input field
        self.seccm_y_length_input = QLineEdit()
        self.seccm_y_length_input.setText(self.seccm_options['y_length'])
        form_layout.addRow('y_length (mm):', self.seccm_y_length_input)

        # Retracting height
        self.seccm_retract_input = QLineEdit()
        self.seccm_retract_input.setText(self.seccm_options['retract_h'])
        form_layout.addRow('Retracting height (mm):', self.seccm_retract_input)

        # Retracting speed
        self.seccm_retract_speed_input = QLineEdit()
        self.seccm_retract_speed_input.setText(self.seccm_options['retract_s'])
        form_layout.addRow('Retracting speed (mm/s):', self.seccm_retract_speed_input)

        # Dialog Buttons
        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_seccm_options(dialog))
        button_box.rejected.connect(dialog.reject)

        # Connect Save and Open buttons
        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_seccm_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_seccm_options_from_file)

        form_layout.addRow(button_box)


        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_seccm_options_to_file(self):
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save SECCM Options and Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)")
        if file_name:
            try:
                # Gather options
                options = {
                    'points_number': self.seccm_points_num_selector.currentText(),
                    'tech_measure': self.seccm_tech_measure_input.text(),
                    'x_width': self.seccm_x_width_input.text(),
                    'y_length': self.seccm_y_length_input.text(),
                    'retract_h': self.seccm_retract_input.text(),
                    'retract_s': self.seccm_retract_speed_input.text(),
                }

                if 'CP' in self.seccm_options['tech_measure']:
                    # cp options
                    options_cp = {
                        'vs_init': self.tech_cp_vs_init_select.currentText(),
                        'current_applied': self.tech_cp_current_input.text(),
                        'duration': self.tech_cp_duration_input.text(),
                        'record_dT': self.tech_cp_record_dt_input.text(),
                        'record_dE': self.tech_cp_record_dE_input.text(),
                        'N_Cycles': self.tech_cp_n_cycles_input.text(),
                    }

                if 'CA' in self.seccm_options['tech_measure']:
                    # ca options
                    options_ca = {
                        'vs_init': self.tech_ca_vs_init_select.currentText(),
                        'voltage_applied': self.tech_ca_voltage_input.text(),
                        'duration': self.tech_ca_duration_input.text(),
                        'record_dT': self.tech_ca_record_dt_input.text(),
                        'record_dI': self.tech_ca_record_dI_input.text(),
                        'N_Cycles': self.tech_ca_n_cycles_input.text(),
                    }
                
                if 'PEIS' in self.seccm_options['tech_measure']:
                    # peis options
                    options_peis = {
                        'vs_init': self.peis_vs_init_select.currentText(),
                        'init_voltage_step': self.peis_init_volt_step_input.text(),
                        'duration_step': self.peis_duration_step_input.text(),
                        'record_dt': self.peis_record_dt_input.text(),
                        'record_dI': self.peis_record_dI_input.text(),
                        'final_freq': self.peis_final_freq_input.text(),
                        'initial_freq': self.peis_initial_freq_input.text(),
                        'sweep': self.peis_sweep_select.currentText(),
                        'amplitude_voltage': self.peis_amplitude_voltage_input.text(),
                        'freq_number': self.peis_freq_number_input.text(),
                        'avg_n': self.peis_avg_n_input.text(),
                        'correction': self.peis_correction_select.currentText(),
                        'wait_steady': self.peis_wait_steady_input.text(),
                    }

                if 'CV' in self.seccm_options['tech_measure']:
                    # cv options
                    options_cv = {
                        'Ei': self.cv_ei_input.text(),
                        'E1': self.cv_e1_input.text(),
                        'E2': self.cv_e2_input.text(),
                        'Ef': self.cv_ef_input.text(),
                        'Scan rate': self.cv_scan_rate_input.text(),
                        'Record_every_dE': self.cv_record_dE_input.text(),
                        'Average_over_dE': self.cv_average_dE_selector.currentText(),
                        'N_Cycles': self.cv_n_cycles_input.text(),
                    }

                # Gather results
                """results = {
                    'Time (s)': self.seccm_time,
                    'Ewe (V)': self.seccm_Ewe,
                    'Iwe (A)': self.seccm_Iwe,
                    'Cycle (N)': self.seccm_cycle,
                }"""
                # Get results from technique used in the previous experiment
                if 'CV' in self.seccm_options['tech_measure']:
                    #print("in  cv")
                    results_seccm_cv = []
                    try:
                        with open('seccm_cv_file.csv', 'r', newline='') as csvfile:
                            reader = csv.DictReader(csvfile)
                            for row in reader:
                                results_seccm_cv.append(row)
                    except Exception as read_error:
                        # If reading fails, you can decide whether to continue or show an error.
                        raise Exception(f"Failed to read 'seccm_cv_file.csv': {read_error}")

                    # Determine format based on the selected filter or file extension
                    if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                        # Save data as JSON
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM CV options and results saved successfully in JSON format.\n{file_name}"
                    elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                        # Save data as CSV
                        # we write a two-part CSV file:
                        # 1. The options section as key/value pairs.
                        # 2. A blank row, then the results (read from seccm_cv_file.csv).
                        with open(file_name, 'w', newline='') as csvfile:
                            csv_writer = csv.writer(csvfile)

                            # Write options.
                            csv_writer.writerow(["Option", "Value"])
                            for key, value in options.items():
                                csv_writer.writerow([key, value])
                            csv_writer.writerow([])  # Empty row for separation.

                            # Write results.
                            if results_seccm_cv:
                                # Write header row using keys from the first results row.
                                headers = list(results_seccm_cv[0].keys())
                                csv_writer.writerow(headers)
                                # Write each row of results.
                                for row in results_seccm_cv:
                                    csv_writer.writerow([row[h] for h in headers])
                            else:
                                csv_writer.writerow(["No results data found in seccm_cv_file.csv"])

                        message = f"SECCM_CV options and results saved successfully in CSV format.\n{file_name}"
                    else:
                        # Fallback to JSON if no valid filter is detected.
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM options and results saved successfully in JSON format.\n{file_name}"
                    
                    QMessageBox.information(self, "Save Options and Results", message)

                if 'PEIS' in self.seccm_options['tech_measure']:
                    print("in  peis")
                    results_seccm_peis = []
                    try:
                        with open('seccm_peis_p2.csv', 'r', newline='') as csvfile:
                            reader = csv.DictReader(csvfile)
                            for row in reader:
                                results_seccm_peis.append(row)
                    except Exception as read_error:
                        # If reading fails, you can decide whether to continue or show an error.
                        raise Exception(f"Failed to read 'seccm_peis_p2.csv': {read_error}")

                    # Determine format based on the selected filter or file extension
                    if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                        # Save data as JSON
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM PEIS options and results saved successfully in JSON format.\n{file_name}"
                    elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                        # Save data as CSV
                        # 1. A blank row, then the results (read from seccm_peis_p2.csv).
                        with open(file_name, 'w', newline='') as csvfile:
                            csv_writer = csv.writer(csvfile)

                            # Write options.
                            csv_writer.writerow(["Option", "Value"])
                            for key, value in options.items():
                                csv_writer.writerow([key, value])
                            csv_writer.writerow([])  # Empty row for separation.

                            # Write results.
                            if results_seccm_peis:
                                # Write header row using keys from the first results row.
                                headers = list(results_seccm_peis[0].keys())
                                csv_writer.writerow(headers)
                                # Write each row of results.
                                for row in results_seccm_peis:
                                    csv_writer.writerow([row[h] for h in headers])
                            else:
                                csv_writer.writerow(["No results data found in seccm_peis_p2.csv"])

                        message = f"SECCM PEIS options and results saved successfully in CSV format.\n{file_name}"
                    else:
                        # Fallback to JSON if no valid filter is detected.
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM options and results saved successfully in JSON format.\n{file_name}"
                    
                    QMessageBox.information(self, "Save Options and Results", message)

                
                if 'CP' in self.seccm_options['tech_measure']:
                    print("in  cp")
                    results_seccm_cp = []
                    try:
                        with open('seccm_cp_file.csv', 'r', newline='') as csvfile:
                            reader = csv.DictReader(csvfile)
                            for row in reader:
                                results_seccm_cp.append(row)
                    except Exception as read_error:
                        # If reading fails, you can decide whether to continue or show an error.
                        raise Exception(f"Failed to read 'seccm_cp_file.csv': {read_error}")

                    # Determine format based on the selected filter or file extension
                    if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                        # Save data as JSON
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM CP options and results saved successfully in JSON format.\n{file_name}"
                    elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                        # Save data as CSV
                        # we write a two-part CSV file:
                        # 1. The options section as key/value pairs.
                        # 2. A blank row, then the results (read from seccm_cp_file.csv).
                        with open(file_name, 'w', newline='') as csvfile:
                            csv_writer = csv.writer(csvfile)

                            # Write options.
                            csv_writer.writerow(["Option", "Value"])
                            for key, value in options.items():
                                csv_writer.writerow([key, value])
                            csv_writer.writerow([])  # Empty row for separation.

                            # Write results.
                            if results_seccm_cp:
                                # Write header row using keys from the first results row.
                                headers = list(results_seccm_cp[0].keys())
                                csv_writer.writerow(headers)
                                # Write each row of results.
                                for row in results_seccm_cp:
                                    csv_writer.writerow([row[h] for h in headers])
                            else:
                                csv_writer.writerow(["No results data found in seccm_cp_file.csv"])

                        message = f"SECCM_CP options and results saved successfully in CSV format.\n{file_name}"
                    else:
                        # Fallback to JSON if no valid filter is detected.
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM options and results saved successfully in JSON format.\n{file_name}"

                    QMessageBox.information(self, "Save Options and Results", message)
                
                if 'CA' in self.seccm_options['tech_measure']:
                    print("in  ca")
                    results_seccm_ca = []
                    try:
                        with open('seccm_ca_file.csv', 'r', newline='') as csvfile:
                            reader = csv.DictReader(csvfile)
                            for row in reader:
                                results_seccm_ca.append(row)
                    except Exception as read_error:
                        # If reading fails, you can decide whether to continue or show an error.
                        raise Exception(f"Failed to read 'seccm_ca_file.csv': {read_error}")

                    # Determine format based on the selected filter or file extension
                    if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                        # Save data as JSON
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM CA options and results saved successfully in JSON format.\n{file_name}"
                    elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                        # Save data as CSV
                        # we write a two-part CSV file:
                        # 1. The options section as key/value pairs.
                        # 2. A blank row, then the results (read from seccm_ca_file.csv).
                        with open(file_name, 'w', newline='') as csvfile:
                            csv_writer = csv.writer(csvfile)

                            # Write options.
                            csv_writer.writerow(["Option", "Value"])
                            for key, value in options.items():
                                csv_writer.writerow([key, value])
                            csv_writer.writerow([])  # Empty row for separation.

                            # Write results.
                            if results_seccm_ca:
                                # Write header row using keys from the first results row.
                                headers = list(results_seccm_ca[0].keys())
                                csv_writer.writerow(headers)
                                # Write each row of results.
                                for row in results_seccm_ca:
                                    csv_writer.writerow([row[h] for h in headers])
                            else:
                                csv_writer.writerow(["No results data found in seccm_ca_file.csv"])

                        message = f"SECCM_CA options and results saved successfully in CSV format.\n{file_name}"
                    else:
                        # Fallback to JSON if no valid filter is detected.
                        with open(file_name, 'w') as file:
                            json.dump(data_to_save, file, indent=4)
                        message = f"SECCM options and results saved successfully in JSON format.\n{file_name}"

                    QMessageBox.information(self, "Save Options and Results", message)

                
                results_seccm_approach = []
                results_seccm_retract = []
                try:
                    with open('seccm_approach_file.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results_seccm_approach.append(row)

                    with open('seccm_retract_file.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results_seccm_retract.append(row)
                except Exception as read_error:
                    # If reading fails, you can decide whether to continue or show an error.
                    raise Exception(f"Failed to read 'seccm_retract_file.csv'or 'seccm_approach_file.csv': {read_error}")



                # Combine options and results
                data_to_save = {
                    'options': options,
                    #'results': results,
                }

                # Determine format based on the selected filter or file extension for approach
                if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                    # Save data as JSON
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"SECCM Approach options and results saved successfully in JSON format.\n{file_name}"
                elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                    # Save data as CSV
                    # we write a two-part CSV file:
                    # 1. The options section as key/value pairs.
                    # 2. A blank row, then the results (read from electro_cp.csv).
                    with open(file_name, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        # Write options.
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Empty row for separation.

                        # Write results.
                        if results_seccm_approach:
                            # Write header row using keys from the first results row.
                            headers = list(results_seccm_approach[0].keys())
                            csv_writer.writerow(headers)
                            # Write each row of results.
                            for row in results_seccm_approach:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in seccm_approach_file.csv"])

                    message = f"SECCM Approach options and results saved successfully in CSV format.\n{file_name}"
                else:
                    # Fallback to JSON if no valid filter is detected.
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"SECCM Approach options and results saved successfully in JSON format.\n{file_name}"

                # Determine format based on the selected filter or file extension for retract
                if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                    # Save data as JSON
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"SECCM Retract options and results saved successfully in JSON format.\n{file_name}"
                elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                    # Save data as CSV
                    # we write a two-part CSV file:
                    # 1. The options section as key/value pairs.
                    # 2. A blank row, then the results (read from electro_cp.csv).
                    with open(file_name, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        # Write options.
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Empty row for separation.

                        # Write results.
                        if results_seccm_retract:
                            # Write header row using keys from the first results row.
                            headers = list(results_seccm_retract[0].keys())
                            csv_writer.writerow(headers)
                            # Write each row of results.
                            for row in results_seccm_retract:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in seccm_retract_file.csv"])

                    message = f"SECCM retract options and results saved successfully in CSV format.\n{file_name}"
                else:
                    # Fallback to JSON if no valid filter is detected.
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"SECCM Approach options and results saved successfully in JSON format.\n{file_name}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")


    def upload_seccm_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open SECCM Options", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as file:
                    data = json.load(file)

                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain SECCM options.")
                    return
                
                data = options
                self.seccm_options.update(data)
                # Update UI fields
                self.seccm_points_num_selector.setCurrentText(data['points_number'])
                self.seccm_tech_measure_input.setText(data['tech_measure'])
                self.seccm_x_width_input.setText(data['x_width'])
                self.seccm_y_length_input.setText(data['y_length'])
                self.seccm_retract_input.setText(data['retract_h'])
                self.seccm_retract_speed_input.setText(data['retract_s'])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load options: {e}")


    def save_seccm_options(self, dialog):
        list_points = ['CV', 'PEIS', 'CP', 'CA']
        self.seccm_options['points_number'] = self.seccm_points_num_selector.currentText()
        self.seccm_options['tech_measure'] = self.seccm_tech_measure_input.text()
        self.seccm_options['x_width'] = self.seccm_x_width_input.text()
        self.seccm_options['y_length'] = self.seccm_y_length_input.text()
        self.seccm_options['retract_h'] = self.seccm_retract_input.text()
        self.seccm_options['retract_s'] = self.seccm_retract_speed_input.text()

        # You can add validation here if needed
        # check if self.seccm_options['tech_measure'] contains ','
        if ',' in self.seccm_options['tech_measure']:
            # multiple techniques  at the surface 
            self.seccm_options['tech_measure'] = self.seccm_options['tech_measure'].split(',')

            # check if element of self.seccm_options['tech_measure'] is in list_points
            for tech in self.seccm_options['tech_measure']:
                if tech not in list_points:
                    QMessageBox.warning(self, "Invalid Technique", f"Invalid technique '{tech}'. Please choose from: {', '.join(list_points)}")
                    return False
        else: 
            # single technique at the surface
            self.seccm_options['tech_measure'] = []
            self.seccm_options['tech_measure'].append(self.seccm_tech_measure_input.text())
        
        if 'CV' in self.seccm_options['tech_measure']:
            print("in  cv")
        if 'PEIS' in self.seccm_options['tech_measure']:
            print("in  peis")
        if 'CP' in self.seccm_options['tech_measure']:
            print("in  cp")
        
        

        dialog.accept()

    def open_cv_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Cyclic Voltammetry-CV Options')

        form_layout = QFormLayout()

        # CV Ei Input Field
        self.cv_ei_input = QLineEdit()
        self.cv_ei_input.setText(self.cv_options['Ei'])
        form_layout.addRow('Ei (V):', self.cv_ei_input)

        # CV E1 Input Field
        self.cv_e1_input = QLineEdit()
        self.cv_e1_input.setText(self.cv_options['E1'])
        form_layout.addRow('E1 (V):', self.cv_e1_input)

        # CV E2 Input Field
        self.cv_e2_input = QLineEdit()
        self.cv_e2_input.setText(self.cv_options['E2'])
        form_layout.addRow('E2 (V):', self.cv_e2_input)

        # CV Ef Input Field
        self.cv_ef_input = QLineEdit()
        self.cv_ef_input.setText(self.cv_options['Ef'])
        form_layout.addRow('Ef (V):', self.cv_ef_input)

        # CV Scan Rate Input Field
        self.cv_scan_rate_input = QLineEdit()
        self.cv_scan_rate_input.setText(self.cv_options['Scan rate'])
        form_layout.addRow('Scan_rate (V/s):', self.cv_scan_rate_input)

        # CV Record dE Input Field
        self.cv_record_dE_input = QLineEdit()
        self.cv_record_dE_input.setText(self.cv_options['Record_every_dE'])
        form_layout.addRow('Record_dE:', self.cv_record_dE_input)

        # CV Average over dE selection Field
        bool_choices = ['True','False']
        self.cv_average_dE_selector = QComboBox()
        self.cv_average_dE_selector.addItems(bool_choices)
        self.cv_average_dE_selector.setCurrentText(self.cv_options['Average_over_dE'])
        form_layout.addRow('Average over dE:', self.cv_average_dE_selector)

        # CV N_Cycles Input Field
        self.cv_n_cycles_input = QLineEdit()
        self.cv_n_cycles_input.setText(self.cv_options['N_Cycles'])
        form_layout.addRow('N_Cycles:', self.cv_n_cycles_input)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_cv_options(dialog))
        button_box.rejected.connect(dialog.reject)

        # Connect Save and Open buttons
        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_cv_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_cv_options_from_file)

        form_layout.addRow(button_box)


        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_cv_options_to_file(self):
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save CP Options and Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)")
        if file_name:
            try:
                # Gather options
                options = {
                    'Ei': self.cv_ei_input.text(),
                    'E1': self.cv_e1_input.text(),
                    'E2': self.cv_e2_input.text(),
                    'Ef': self.cv_ef_input.text(),
                    'Scan rate': self.cv_scan_rate_input.text(),
                    'Record_every_dE': self.cv_record_dE_input.text(),
                    'Average_over_dE': self.cv_average_dE_selector.currentText(),
                    'N_Cycles': self.cv_n_cycles_input.text(),
                }

                # Gather results
                """results = {
                    'Time (s)': self.cv_time,
                    'Ewe (V)': self.cv_Ewe,
                    'Iwe (A)': self.cv_Iwe,
                    'Cycle (N)': self.cv_cycle,
                }"""
                results = []
                try:
                    with open('electro_cv.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    # If reading fails, you can decide whether to continue or show an error.
                    raise Exception(f"Failed to read 'electro_cv.csv': {read_error}")

                # Combine options and results
                data_to_save = {
                    'options': options,
                    'results': results,
                }

                # Determine format based on the selected filter or file extension
                if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                    # Save data as JSON
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"CV options and results saved successfully in JSON format.\n{file_name}"
                elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                    # Save data as CSV
                    # we write a two-part CSV file:
                    # 1. The options section as key/value pairs.
                    # 2. A blank row, then the results (read from electro_cp.csv).
                    with open(file_name, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        # Write options.
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Empty row for separation.

                        # Write results.
                        if results:
                            # Write header row using keys from the first results row.
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            # Write each row of results.
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_cv.csv"])

                    message = f"CV options and results saved successfully in CSV format.\n{file_name}"
                else:
                    # Fallback to JSON if no valid filter is detected.
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"CV options and results saved successfully in JSON format.\n{file_name}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")

    def upload_cv_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open CV Options", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as file:
                    data = json.load(file)

                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain CV options.")
                    return
                
                data = options
                self.cv_options.update(data)
                # Update UI fields
                self.cv_ei_input.setText(data['Ei'])
                self.cv_e1_input.setText(data['E1'])
                self.cv_e2_input.setText(data['E2'])
                self.cv_ef_input.setText(data['Ef'])
                self.cv_scan_rate_input.setText(data['Scan rate'])
                self.cv_record_dE_input.setText(data['Record_every_dE'])
                self.cv_average_dE_selector.setCurrentText(data['Average_over_dE'])
                self.cv_n_cycles_input.setText(data['N_Cycles'])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load options: {e}")


    def save_cv_options(self, dialog):
        # Save the values
        self.cv_options['Ei'] = self.cv_ei_input.text()
        self.cv_options['E1'] = self.cv_e1_input.text()
        self.cv_options['E2'] = self.cv_e2_input.text()
        self.cv_options['Ef'] = self.cv_ef_input.text()
        self.cv_options['Scan rate'] = self.cv_scan_rate_input.text()
        self.cv_options['Record_every_dE'] = self.cv_record_dE_input.text()
        self.cv_options['Average_over_dE'] = self.cv_average_dE_selector.currentText()
        self.cv_options['N_Cycles'] = self.cv_n_cycles_input.text()

        # You can add validation here if needed
        dialog.accept()
        



    def open_approach_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Approach Scan Options')

        form_layout = QFormLayout()

        # turn to ocv
        bool_choices = ['False','True']
        # vs_init
        self.vs_init_select = QComboBox()
        self.vs_init_select.addItems(bool_choices)
        self.vs_init_select.setCurrentText(self.approach_options['vs_init'])
        form_layout.addRow('vs_init:', self.vs_init_select)


        # Approach Speed Input Field
        self.approach_speed_input = QLineEdit()
        self.approach_speed_input.setText(self.approach_options['approach_speed'])
        form_layout.addRow('Approach Speed (mm/s):', self.approach_speed_input)

        # Voltage Applied Input Field
        self.voltage_applied_input = QLineEdit()
        self.voltage_applied_input.setText(self.approach_options['voltage_applied'])
        form_layout.addRow('Voltage Applied (V):', self.voltage_applied_input)

        # Estimated Approach Time Input Field
        self.estimated_approach_time_input = QLineEdit()
        self.estimated_approach_time_input.setText(self.approach_options['estimated_approach_time'])
        form_layout.addRow('Estimated Approach Time (s):', self.estimated_approach_time_input)

        # Spike Threshold Input Field
        self.spike_threshold_input = QLineEdit()
        self.spike_threshold_input.setText(self.approach_options['spike_threshold'])
        form_layout.addRow('Spike Threshold (A):', self.spike_threshold_input)

        # Dialog Buttons
        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        

        button_box.accepted.connect(lambda: self.save_approach_options(dialog))
        button_box.rejected.connect(dialog.reject)

        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_approach_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_approach_options_from_file)

        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_approach_options_to_file(self):
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save CP Options and Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)")
        if file_name:
            try:
                # Gather options
                options = {
                    'vs_init': self.vs_init_select.currentText(),
                    'approach_speed': self.approach_speed_input.text(),
                    'voltage_applied': self.voltage_applied_input.text(),
                    'estimated_approach_time': self.estimated_approach_time_input.text(),
                    'spike_threshold': self.spike_threshold_input.text(),
                }

                # Gather results
                """results = {
                    'Time (s)': self.ca_time,
                    'Ewe (V)': self.ca_Ewe,
                    'Iwe (A)': self.ca_Iwe,
                    'Cycle (N)': self.ca_cycle,
                }"""
                results = []
                try:
                    with open('approach_data.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    # If reading fails, you can decide whether to continue or show an error.
                    raise Exception(f"Failed to read 'approach_data.csv': {read_error}")

                # Combine options and results
                data_to_save = {
                    'options': options,
                    'results': results,
                }

                # Determine format based on the selected filter or file extension
                if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                    # Save data as JSON
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"Approach options and results saved successfully in JSON format.\n{file_name}"
                elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                    # Save data as CSV
                    # we write a two-part CSV file:
                    # 1. The options section as key/value pairs.
                    # 2. A blank row, then the results (read from approach_data.csv).
                    with open(file_name, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        # Write options.
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Empty row for separation.

                        # Write results.
                        if results:
                            # Write header row using keys from the first results row.
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            # Write each row of results.
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in approach_data.csv"])

                    message = f"Approach options and results saved successfully in CSV format.\n{file_name}"
                else:
                    # Fallback to JSON if no valid filter is detected.
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"Approach options and results saved successfully in JSON format.\n{file_name}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")


    def upload_approach_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Approach Options", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as file:
                    data = json.load(file)

                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain Approach options.")
                    return
                
                data = options

                self.approach_options.update(data)
                # Update UI fields
                self.vs_init_select.setCurrentText(data['vs_init'])
                self.approach_speed_input.setText(data['approach_speed'])
                self.voltage_applied_input.setText(data['voltage_applied'])
                self.estimated_approach_time_input.setText(data['estimated_approach_time'])
                self.spike_threshold_input.setText(data['spike_threshold'])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load options: {e}")


    def save_approach_options(self, dialog):
        # Save the values
        self.approach_options['vs_init'] = self.vs_init_select.currentText()
        self.approach_options['approach_speed'] = self.approach_speed_input.text()
        self.approach_options['voltage_applied'] = self.voltage_applied_input.text()
        self.approach_options['estimated_approach_time'] = self.estimated_approach_time_input.text()
        self.approach_options['spike_threshold'] = self.spike_threshold_input.text()

        #print(f"vs_int = {self.approach_options['vs_init']}")

        # You can add validation here if needed
        dialog.accept()

    def open_line_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Line Scan Options')

        form_layout = QFormLayout()

        # X-axis settings
        self.line_x_length_input = QLineEdit()
        self.line_x_length_input.setText(self.line_options['x_length'])
        form_layout.addRow('X length (mm): ', self.line_x_length_input)

        self.line_x_speed_input = QLineEdit()
        self.line_x_speed_input.setText(self.line_options['x_speed'])
        form_layout.addRow('X speed (mm/s): ', self.line_x_speed_input)

        # Y-axis settings
        self.line_y_length_input = QLineEdit()
        self.line_y_length_input.setText(self.line_options['y_length'])
        form_layout.addRow('Y length (mm): ', self.line_y_length_input)

        self.line_y_speed_input = QLineEdit()
        self.line_y_speed_input.setText(self.line_options['y_speed'])
        form_layout.addRow('Y speed (mm/s): ', self.line_y_speed_input)

        # Scan Speed Input Field
        self.scan_speed_input = QLineEdit()
        self.scan_speed_input.setText(self.line_options['scan_speed'])
        form_layout.addRow('Scan Speed (mm/s):', self.scan_speed_input)

        # Voltage Applied Input Field
        self.voltage_applied_line_input = QLineEdit()
        self.voltage_applied_line_input.setText(self.line_options['voltage_applied'])
        form_layout.addRow('Voltage Applied (V):', self.voltage_applied_line_input)

        # Estimated Line Time Input Field
        self.estimated_line_time_input = QLineEdit()
        self.estimated_line_time_input.setText(self.line_options['estimated_line_time'])
        form_layout.addRow('Estimated Line Time (s):', self.estimated_line_time_input)


        # Dialog Buttons
        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Save | QDialogButtonBox.Open)
        button_box.accepted.connect(lambda: self.save_line_options(dialog))
        button_box.rejected.connect(dialog.reject)

        # Connect Save and Open buttons
        button_box.button(QDialogButtonBox.Save).clicked.connect(self.save_line_options_to_file)
        open_button = button_box.button(QDialogButtonBox.Open)
        open_button.clicked.disconnect()
        open_button.clicked.connect(self.upload_line_options_from_file)

        form_layout.addRow(button_box)


        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_line_options_to_file(self):
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Line Scan Options and Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv)")
        if file_name:
            try:
                options = {
                    'x_length': self.line_x_length_input.text(),
                    'x_speed': self.line_x_speed_input.text(),
                    'y_length': self.line_y_length_input.text(),
                    'y_speed': self.line_y_speed_input.text(),
                    'scan_speed': self.scan_speed_input.text(),
                    'voltage_applied': self.voltage_applied_line_input.text(),
                    'estimated_line_time': self.estimated_line_time_input.text(),
                }

                """results = {
                    'Time (s)': self.line_time,  # Make sure you have these attributes
                    'Ewe (V)': self.line_Ewe,
                    'Iwe (A)': self.line_Iwe,
                    'Cycle (N)': self.line_cycle,
                }"""
                results = []
                try:
                    with open('electro_line_scan.csv', 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        for row in reader:
                            results.append(row)
                except Exception as read_error:
                    # If reading fails, you can decide whether to continue or show an error.
                    raise Exception(f"Failed to read 'electro_line_scan.csv': {read_error}")

                data_to_save = {
                    'options': options,
                    'results': results,
                }

                # Determine format based on the selected filter or file extension
                if selected_filter.startswith("JSON") or file_name.endswith(".json"):
                    # Save data as JSON
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"Line Scan options and results saved successfully in JSON format.\n{file_name}"
                elif selected_filter.startswith("CSV") or file_name.endswith(".csv"):
                    # Save data as CSV
                    # we write a two-part CSV file:
                    # 1. The options section as key/value pairs.
                    # 2. A blank row, then the results (read from electro_cp.csv).
                    with open(file_name, 'w', newline='') as csvfile:
                        csv_writer = csv.writer(csvfile)

                        # Write options.
                        csv_writer.writerow(["Option", "Value"])
                        for key, value in options.items():
                            csv_writer.writerow([key, value])
                        csv_writer.writerow([])  # Empty row for separation.

                        # Write results.
                        if results:
                            # Write header row using keys from the first results row.
                            headers = list(results[0].keys())
                            csv_writer.writerow(headers)
                            # Write each row of results.
                            for row in results:
                                csv_writer.writerow([row[h] for h in headers])
                        else:
                            csv_writer.writerow(["No results data found in electro_line_scan.csv"])

                    message = f"Line Scan options and results saved successfully in CSV format.\n{file_name}"
                else:
                    # Fallback to JSON if no valid filter is detected.
                    with open(file_name, 'w') as file:
                        json.dump(data_to_save, file, indent=4)
                    message = f"Line Scan options and results saved successfully in JSON format.\n{file_name}"

                QMessageBox.information(self, "Save Options and Results", message)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save options and results: {e}")


    def upload_line_options_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Line Scan Options", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, 'r') as file:
                    data = json.load(file)


                # Update options only
                options = data.get('options', {})
                if not options:
                    QMessageBox.warning(self, "No Options Found", "The selected file does not contain Line options.")
                    return
                
                data = options
                self.line_options.update(data)
                # Update UI fields
                self.line_x_length_input.setText(data['x_length'])
                self.line_x_speed_input.setText(data['x_speed'])
                self.line_y_length_input.setText(data['y_length'])
                self.line_y_speed_input.setText(data['y_speed'])
                self.scan_speed_input.setText(data['scan_speed'])
                self.voltage_applied_line_input.setText(data['voltage_applied'])
                self.estimated_line_time_input.setText(data['estimated_line_time'])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load options: {e}")


    def save_line_options(self, dialog):
        # Save the values
        self.line_options['x_length'] = self.line_x_length_input.text()
        self.line_options['x_speed'] = self.line_x_speed_input.text()
        self.line_options['y_length'] = self.line_y_length_input.text()
        self.line_options['y_speed'] = self.line_y_speed_input.text()
        self.line_options['scan_speed'] = self.scan_speed_input.text()
        self.line_options['voltage_applied'] = self.voltage_applied_line_input.text()
        self.line_options['estimated_line_time'] = self.estimated_line_time_input.text()

        # You can add validation here if needed
        dialog.accept()


    def create_macro_box(self):
        group_box = QGroupBox('Macro')
        main_layout = QVBoxLayout()

        # -------------------------------
        # Macro File Section
        # -------------------------------
        self.macro_file_label = QLabel('No Macro File Selected')
        self.macro_file_label.setToolTip('Displays the selected macro file.')
        upload_macro_btn = QPushButton('Upload Macro File')
        upload_macro_btn.setToolTip('Click to choose a macro file.')
        upload_macro_btn.clicked.connect(self.upload_macro_file)

        main_layout.addWidget(self.macro_file_label)
        main_layout.addWidget(upload_macro_btn)
        #main_layout.addSpacing(5)

        # Add new toggle button for macro content window
        self.toggle_macro_btn = QPushButton('Show/Hide')
        self.toggle_macro_btn.setToolTip('Toggle to show or hide the macro file content window.')
        self.toggle_macro_btn.clicked.connect(self.toggle_macro_window)
        self.toggle_macro_btn.setEnabled(False)
        main_layout.addWidget(self.toggle_macro_btn)


        # -------------------------------
        # MPS/Options Files Section
        # -------------------------------
        mps_label = QLabel('MPS/Options Files:')
        mps_label.setToolTip('List of selected MPS/Options files.')
        main_layout.addWidget(mps_label)

        self.mps_file_list = QListWidget()
        main_layout.addWidget(self.mps_file_list)

        upload_mps_btn = QPushButton('Upload MPS/Options Files')
        upload_mps_btn.setToolTip('Click to choose MPS/Options files.')
        upload_mps_btn.clicked.connect(self.upload_mps_options_files)

        main_layout.addWidget(upload_mps_btn)

        #main_layout.addSpacing(5)

        # -------------------------------
        # Playback Controls (Icon Only)
        # -------------------------------
        playback_layout = QHBoxLayout()
        style = self.style()

        # Create instance attributes for the playback buttons and disable them initially.
        self.play_btn = QPushButton()
        self.play_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.play_btn.setIconSize(QSize(24, 24))
        self.play_btn.setToolTip('Play Macro')
        self.play_btn.clicked.connect(self.play_macro)
        self.play_btn.setEnabled(False)
        playback_layout.addWidget(self.play_btn)

        self.pause_btn = QPushButton()
        self.pause_btn.setIcon(style.standardIcon(QStyle.SP_MediaPause))
        self.pause_btn.setIconSize(QSize(24, 24))
        self.pause_btn.setToolTip('Pause Macro')
        self.pause_btn.clicked.connect(self.pause_macro)
        self.pause_btn.setEnabled(False)
        playback_layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(style.standardIcon(QStyle.SP_MediaStop))
        self.stop_btn.setIconSize(QSize(24, 24))
        self.stop_btn.setToolTip('Stop Macro')
        self.stop_btn.clicked.connect(self.stop_macro)
        #playback_layout.setAlignment(Qt.AlignLeft)
        self.stop_btn.setEnabled(False)
        playback_layout.addWidget(self.stop_btn)

        main_layout.addLayout(playback_layout)

        group_box.setLayout(main_layout)
        return group_box

    # -------------------------------
    # Slot Methods
    # -------------------------------
    def upload_macro_file(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Macro File", "", "Macro Files (*.txt *.macro);;All Files (*)", options=options)
        if file_name:
            self.macro_file_label.setText(file_name)
            try:
                with open(file_name, 'r') as f:
                    self.macro_content = f.read()
            except Exception as e:
                self.macro_content = "Error reading file: " + str(e)
            self.show_macro_content_window()
            # Enable playback controls when a macro file is uploaded
            self.play_btn.setEnabled(True)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            # Enable the toggle and edit button for macro content window
            self.toggle_macro_btn.setEnabled(True)
            # Initialize editing state flag
            self.macro_edit_mode = False

    def edit_macro_content(self):
        # Check if the macro content dialog exists
        if hasattr(self, 'macro_text_edit') and hasattr(self, 'macro_text_edit'):
            if not self.macro_edit_mode:
                # Enable editing
                self.macro_text_edit.setReadOnly(False)
                self.edit_macro_btn.setText("Save Edits")
                self.macro_edit_mode = True
                # Save file when Save edits clicked
                self.edit_macro_btn.clicked.connect(self.save_macro_edits)
            else:
                # Disable editing and update macro content
                self.macro_text_edit.setReadOnly(True)
                self.macro_content = self.macro_text_edit.toPlainText()
                self.edit_macro_btn.setText("Edit Macro")
                self.macro_edit_mode = False

    def save_macro_edits(self):
        # Save the edited macro content to the file
        file_name = self.macro_file_label.text()
        try:
            with open(file_name, 'w') as f:
                f.write(self.macro_content)
        except Exception as e:
            print("Error saving file: " + str(e))

                

    def upload_mps_options_files(self):
        options = QFileDialog.Options()
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select MPS/Options Files", "", "All Files (*)", options=options)
        if files:
            for file_path in files:
                self.add_mps_file(file_path)

    def add_mps_file(self, file_path):
        item = QListWidgetItem(self.mps_file_list)
        file_widget = FileItemWidget(file_path, self.remove_file_item)
        item.setSizeHint(file_widget.sizeHint())
        self.mps_file_list.addItem(item)
        self.mps_file_list.setItemWidget(item, file_widget)

    def remove_file_item(self, file_widget):
        count = self.mps_file_list.count()
        for i in range(count):
            item = self.mps_file_list.item(i)
            widget = self.mps_file_list.itemWidget(item)
            if widget == file_widget:
                self.mps_file_list.takeItem(i)
                break

    def play_macro(self):
        print("Playing macro...")
        try:
            # Create and start the macro executor thread
            self.macro_executor_thread = MacroExecutorThread(self.macro_content)
            self.macro_executor_thread.highlight_line_signal.connect(self.highlight_line)
            self.macro_executor_thread.start()
        except ImportError as e:
            print("Error importing MacroInterpreter:", e)
            return

    def pause_macro(self):
        if hasattr(self, 'macro_executor_thread'):
            if not self.macro_executor_thread._paused:
                self.macro_executor_thread.pause()
                print("Macro paused.")
                # Optionally, change the pause button text to "Resume"
                self.pause_btn.setText("Resume")
            else:
                self.macro_executor_thread.resume()
                print("Macro resumed.")
                self.pause_btn.setText("Pause")

    def stop_macro(self):
        if hasattr(self, 'macro_executor_thread'):
            # Request interruption and wait for the thread to finish
            self.macro_executor_thread.requestInterruption()
            self.macro_executor_thread.wait()
            print("Macro stopped.")
            # Optionally, reset playback buttons or UI state here.
        else:
            print("No macro is running.")

    # -------------------------------
    # Macro Content Window and Highlighting
    # -------------------------------
    def show_macro_content_window(self):
        # Instead of creating and adding a dock widget,
        # create a macro content widget and add it to self.right_layout if it does not exist.
        if not hasattr(self, 'macro_content_widget'):
            self.macro_content_widget = QGroupBox("Macro File Content")
            layout = QVBoxLayout()
            # Macro text edit
            self.macro_text_edit = QTextEdit()
            self.macro_text_edit.setReadOnly(True)
            self.macro_text_edit.setText(self.macro_content)
            layout.addWidget(self.macro_text_edit)
            # Edit Macro button, already moved here from create_macro_box
            self.edit_macro_btn = QPushButton("Edit Macro")
            self.edit_macro_btn.setToolTip("Enable editing of the macro file content.")
            self.edit_macro_btn.clicked.connect(self.edit_macro_content)
            self.edit_macro_btn.setEnabled(True)
            layout.addWidget(self.edit_macro_btn)
            self.macro_content_widget.setLayout(layout)
            # Remove default stretch before adding the widget
            if hasattr(self, 'default_stretch'):
                self.right_layout.removeItem(self.default_stretch)
                del self.default_stretch
            # Add the macro content widget to the right layout.
            self.right_layout.addWidget(self.macro_content_widget)
            #self.right_layout.addStretch()
            
        else:
            # If it already exists, update its content and ensure it is visible.
            self.macro_text_edit.setText(self.macro_content)
            self.macro_content_widget.show()


    def toggle_macro_window(self):
        if hasattr(self, 'macro_content_widget') and self.macro_content_widget.isVisible():
            self.macro_content_widget.hide()
            self.toggle_macro_btn.setText("Show")
            # Add a spacer stretch when the macro content widget is hidden.
            if not hasattr(self, 'macro_content_stretch'):
                self.macro_content_stretch = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
                self.right_layout.addItem(self.macro_content_stretch)
        else:
            # Show the macro widget and remove any stretch spacer.
            if hasattr(self, 'macro_content_widget'):
                self.macro_content_widget.show()
            else:
                self.show_macro_content_window()
            self.toggle_macro_btn.setText("Hide")
            if hasattr(self, 'macro_content_stretch'):
                self.right_layout.removeItem(self.macro_content_stretch)
                del self.macro_content_stretch


    def highlight_line(self, line_number):
        if not hasattr(self, 'macro_text_edit'):
            return

        # Navigate to the beginning of the specified line.
        cursor = self.macro_text_edit.textCursor()
        cursor.movePosition(cursor.Start)
        for _ in range(line_number - 1):
            cursor.movePosition(cursor.Down)
        cursor.select(cursor.LineUnderCursor)

        # Create an extra selection with a vibrant background.
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        # Set a vibrant background color (e.g., a bright yellow or orange)
        selection.format.setBackground(QColor("#FFCC00"))
        # Make sure the background spans the full width of the line.
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)

        # Apply the extra selection so that the line is highlighted.
        self.macro_text_edit.setExtraSelections([selection])

    def create_filter_box(self):
        group_box = QGroupBox('Filter Selection')
        layout = QHBoxLayout()

        i_range_label = QLabel('I-Range:')
        self.i_range_selector = QComboBox()
        self.i_range_selector.addItems(['100pA','1pA', '10pA', '1nA', '10nA', '100nA', '1uA', '10uA', '100uA', '1mA'])

        e_range_label = QLabel('E-Range:')
        self.e_range_selector = QComboBox()
        self.e_range_selector.addItems(['-1V, 1V','-2.5V, 2.5V', '0V, 5V', '-5V, 5V', '0V, 10V', '-5V, 10V', '-10V, 10V'])

        

        bandwidth_label = QLabel('Bandwidth:')
        self.bandwidth_selector = QComboBox()
        self.bandwidth_selector.addItems(['1','2','3', '4','5' ,'6','7', '8','9'])

        layout.addWidget(i_range_label)
        layout.addWidget(self.i_range_selector)
        layout.addWidget(e_range_label)
        layout.addWidget(self.e_range_selector)
        layout.addWidget(bandwidth_label)
        layout.addWidget(self.bandwidth_selector)

        group_box.setLayout(layout)
        return group_box

    def create_motor_position_box(self):
        group_box = QGroupBox('Motor Position')
        layout = QHBoxLayout()

        x_label = QLabel('X:')
        self.x_input = QLineEdit()
        self.x_input.setPlaceholderText('X Position')

        y_label = QLabel('Y:')
        self.y_input = QLineEdit()
        self.y_input.setPlaceholderText('Y Position')

        z_label = QLabel('Z:')
        self.z_input = QLineEdit()
        self.z_input.setPlaceholderText('Z Position')

        layout.addWidget(x_label)
        layout.addWidget(self.x_input)
        layout.addWidget(y_label)
        layout.addWidget(self.y_input)
        layout.addWidget(z_label)
        layout.addWidget(self.z_input)

        group_box.setLayout(layout)
        return group_box

    def update_position_values(self, x, y, z, t):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        self.x_input.setText(f"{x:.4f}")
        self.y_input.setText(f"{y:.4f}")
        self.z_input.setText(f"{z:.4f}")
        """if self.write_seccm_position:
            self.seccm_datadump.write(f"x: {x:.4f}, y: {y:.4f}, z:{z:.4f}\n")
            self.write_seccm_position = False"""
        self.motor_positions_file = open("motor_positions_file.csv", "+a")
        self.motor_positions_file.write(f"{t},{x:.4f},{y:.4f},{z:.4f}\n")
        self.motor_positions_file.close

    
    def update_motor_positions(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        #print("return number"+ self.ser.)
        send_command(self.ser, "pos")
        x,y,z = 0,0,0
        x,y,z = extract_coordinates(read_response(self.ser))

        if(self.controller_settings['motor_pos_unit'] == 'um'):
            # updating values for the positions in um
            self.x_input.setText(f"{x:.4f}")
            self.y_input.setText(f"{y:.4f}")
            self.z_input.setText(f"{z:.4f}")
        else: # In mm
            # updating values for the positions
            self.x_input.setText(f"{x:.4f}")
            self.y_input.setText(f"{y:.4f}")
            self.z_input.setText(f"{z:.4f}")

    def update_current_values(self, state, Ewe, I, lt):
        self.current_i_value = I
        self.current_ewe_value = Ewe
        self.channel_state_value = state
        

        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')

    def update_current_values_seccm(self, state, Ewe, I, lt):
        self.current_i_value = I
        self.current_ewe_value = Ewe
        self.channel_state_value = state
        

        self.i_value_label.setText(f'{self.current_i_value} A')
        self.v_value_label.setText(f'{self.current_ewe_value} V')
        self.retract_values_file = open("retract_values_file.csv", "+a")
        self.retract_values_file.write(f"{lt},{state},{Ewe},{I}")
        self.retract_values_file.close()

    



    def create_output_box(self):
        group_box = QGroupBox('Output')
        layout = QHBoxLayout()
        self.rdp = self.rdp +1
        i_label = QLabel('I:')
        self.i_value_label = QLabel(f'{self.current_i_value} A')

        v_label = QLabel('V:')
        
        self.v_value_label = QLabel(f'{self.current_ewe_value} V')

        layout.addWidget(i_label)
        layout.addWidget(self.i_value_label)
        layout.addWidget(v_label)
        layout.addWidget(self.v_value_label)

        group_box.setLayout(layout)
        return group_box

    def create_stop_button(self):
        stop_button = QPushButton('STOP')
        stop_button.setStyleSheet("background-color: red; color: white; font-size: 18pt;")
        stop_button.clicked.connect(self.stop_button_pressed)
        stop_button.released.connect(self.stop_button_released)
        return stop_button
    
    def stop_button_pressed(self):
        if not hasattr(self, 'ser') or not self.ser.is_open:
            QMessageBox.warning(self, 'Controller Not Connected', 'Please connect the controller first.')
            return
        
        self.stop_all = True
        send_command(self.ser, "stopspeed")
        QMessageBox.information(self,'Stop', 'Everything stopped')


    def stop_button_released(self):
        self.stop_all = False

    def controller_setup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Hardware Setup')

        form_layout = QFormLayout()

        # Unit Selection Field
        units = ['microstep', 'µm', 'mm', 'cm', 'm', 'inch', 'mil']
        self.unit_selector = QComboBox()
        self.unit_selector.addItems(units)
        self.unit_selector.setCurrentText(self.controller_settings['unit'])
        form_layout.addRow('Unit:', self.unit_selector)

        # Pitch Input Field
        self.pitch_input = QLineEdit()
        self.pitch_input.setText(self.controller_settings['pitch'])
        self.pitch_input.setPlaceholderText('Pitch in mm')
        form_layout.addRow('Pitch (mm):', self.pitch_input)

        # Motor position Unit Selection Field
        motor_pos_unit = ['µm', 'mm']
        self.motor_pos_unit_selector = QComboBox()
        self.motor_pos_unit_selector.addItems(motor_pos_unit)
        self.motor_pos_unit_selector.setCurrentText(self.controller_settings['motor_pos_unit'])
        form_layout.addRow('Motor position Unit:', self.motor_pos_unit_selector)

        # Potentiostat_channel_count input field
        self.potentiostat_channel_count = QLineEdit()
        self.potentiostat_channel_count.setText(self.controller_settings['potentiostat_channel_count'])
        form_layout.addRow('Potentiostat number of channels:', self.potentiostat_channel_count)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(lambda: self.save_controller_settings(dialog))
        button_box.rejected.connect(dialog.reject)
        form_layout.addRow(button_box)

        dialog.setLayout(form_layout)
        dialog.exec_()

    def save_controller_settings(self, dialog):
        # Update the controller settings with the selected values
        self.controller_settings['unit'] = self.unit_selector.currentText()
        self.controller_settings['pitch'] = self.pitch_input.text()
        self.controller_settings['motor_pos_unit'] = self.motor_pos_unit_selector.currentText()
        self.controller_settings['potentiostat_channel_count'] = self.potentiostat_channel_count.text()

        # You can add validation here if needed
        if not self.pitch_input.text():
            QMessageBox.warning(self, 'Input Error', 'Pitch value cannot be empty.')
            return

        try:
            float(self.pitch_input.text())
        except ValueError:
            QMessageBox.warning(self, 'Input Error', 'Pitch value must be a number.')
            return

        # Close the dialog
        dialog.accept()


    def open_pdf(self, file_name):
        if not os.path.exists(file_name):
            QMessageBox.warning(self, 'File Not Found', f'The file "{file_name}" does not exist.')
            return
        url = QUrl.fromLocalFile(os.path.abspath(file_name))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, 'Open PDF', 'Could not open PDF file.')

    def open_url(self, url):
        if not url.startswith("http://") and not url.startswith("https://"):
            QMessageBox.warning(self, 'Invalid URL', 'The URL must start with "http://" or "https://".')
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, 'Open URL', 'Could not open the URL.')
        

    
    def closeEvent(self, event):
        # Stop any running experiments
        if hasattr(self, 'experiment_thread') and self.experiment_thread.isRunning():
            self.experiment_thread.stop()
            self.experiment_thread.wait()  # Wait for the thread to finish

        if hasattr(self, 'position_thread') and self.position_thread.isRunning():
            self.position_thread.stop()
            self.position_thread.wait()  # Wait for the thread to finish
        
        if self.potentiostat_connected:
            self.disconnect_potentiostat()
        

        # Close the serial port if it's open
        if hasattr(self, 'ser') and self.ser.is_open:
            try:
                # Stop any speed movement
                with self.write_lock:
                    send_command(self.ser, "stopspeed")
                self.ser.close()
                print("Serial port closed.")
            except Exception as e:
                print(f"Error closing serial port: {e}")
        
        # Perform any other cleanup here

        # Check and delete the files produced
        for file_name in self.files_produced:
            if os.path.exists(file_name):
                try:
                    os.remove(file_name)
                    print(f"Deleted file: {file_name}")
                except Exception as e:
                    print(f"Error deleting file {file_name}: {e}")
        
        # For example, close open files, save settings, etc.
        

        # Accept the event to allow the window to close
        event.accept()

        

    def connect_potentiostat(self):
        # Test parameters, to be adjusted

        verbosity = self.potentiostat_verbosity
        address = self.potentiostat_address
        #address = "10.100.19.1"
        binary_path = self.potentiostat_binary_path
        force_load_firmware = self.potentiostat_force_load_firmware

        def newline():
            print()

        def print_exception(e):
            print(f"{exception_brief(e, verbosity>=2)}")

        def print_messages(ch):
            """Repeatedly retrieve and print messages for a given channel."""
            while True:
                # BL_GetMessage
                msg = self.potentiostat_api.GetMessage(self.potentiostat_id_, ch)
                if not msg:
                    break
                print(msg)

        # determine library file according to Python version (32b/64b)
        if c_is_64b:
            DLL_file = "EClib64.dll"
        else:
            DLL_file = "EClib.dll"
        DLL_path = f"{binary_path}{os.sep}{DLL_file}"

        try:
            newline()
            # API initialize
            self.potentiostat_api = KBIO_api(DLL_path)

            # BL_GetLibVersion
            version = self.potentiostat_api.GetLibVersion()
            print(f"> EcLib version: {version}")
            newline()

            # BL_Connect
            try:
                self.potentiostat_id_, self.potentiostat_device_info = self.potentiostat_api.Connect(address)
                print(f"Potentiostat ID: {self.potentiostat_id_}")
                self.potentiostat_connected = True
            except ConnectionError:
                QMessageBox.critical(self, "Connection Error", "Cannot connect to the devise")
                self.potentiostat_connect_action.setChecked(False)
                self.potentiostat_connected = False
                return

            print(f"> device[{address}] info :")
            #print(self.potentiostat_device_info)
            parts_of_device_info = self.potentiostat_device_info.__str__().split("\n")[0].split(",")
            for part in parts_of_device_info:
                part = part.strip()
                if 'channel' in part.lower():
                    channel_num_str = part.split()[0]
                    try:
                        channel_num = int(channel_num_str)
                    except ValueError:
                        print(f"Unable To convert {channel_num_str} to an integer.")
                    break
            
            self.channel_number = channel_num
            
            # Get the selected channel
            self.potentiostat_channel_selected = int(self.channel_combo.currentText())

            # Check if the channel selected is available on the potentiostat
            if self.potentiostat_channel_selected > channel_num:
                QMessageBox.critical(self, "Invalid Channel Selection", f"Channel {self.potentiostat_channel_selected} is not available on the potentiostat.")
                self.potentiostat_connect_action.setChecked(False)
                self.potentiostat_connected = False
                return

            # Get the channel board type 
            self.potentiostat_board_type = self.potentiostat_api.GetChannelBoardType(self.potentiostat_id_, self.potentiostat_channel_selected)
            

            # Get the firmware filenames based on board type
            match self.potentiostat_board_type:
                case KBIO.BOARD_TYPE.ESSENTIAL.value:
                    firmware_path = "kernel.bin"
                    fpga_path = "Vmp_ii_0437_a6.xlx"
                case KBIO.BOARD_TYPE.PREMIUM.value:
                    firmware_path = "kernel4.bin"
                    fpga_path = "vmp_iv_0395_aa.xlx"
                case KBIO.BOARD_TYPE.DIGICORE.value:
                    firmware_path = "kernel.bin"
                    fpga_path = ""
                case _:
                    print("> Board type detection failed")
                    sys.exit(-1)

            
            # Load firmware
            print(f"> Loading {firmware_path} ...")
            channel_map = self.potentiostat_api.channel_map({self.potentiostat_channel_selected})
            # BL_LoadFirmware
            self.potentiostat_api.LoadFirmware(self.potentiostat_id_, channel_map, firmware=firmware_path, fpga=fpga_path, force=force_load_firmware)
            print("> ... firmware loaded")

            self.start_experiment(perf_current_values, False)

            newline()
            QMessageBox.information(self, 'Potentiostat Connection', 'Potentiostat connected successfully.')
            self.potentiostat_connected = True
            self.potentiostat_connect_action.setIcon(QIcon(resource_path('icons/plug-disconnect.png')))
            self.potentiostat_connect_action.setText('Disconnect Potentiostat')
            self.potentiostat_connect_action.setStatusTip('Disconnect from the potentiostat device')
        except Exception as e:
            print_exception(e)
        
    
    def disconnect_potentiostat(self):
        # Stop any running experiments
        if hasattr(self, 'experiment_thread') and self.experiment_thread.isRunning():
            self.experiment_thread.stop()
            self.experiment_thread.wait()  # Wait for the thread to finish
        self.potentiostat_api.Disconnect(self.potentiostat_id_)
        self.potentiostat_connected = False
        print("Disconnected")

    
def perf_current_values(electro,thread):
        while thread._is_running:
            current_val = electro.potentiostat_api.GetCurrentValues(electro.potentiostat_id_, electro.potentiostat_channel_selected)
            Ewe = current_val.Ewe
            I = current_val.I
            state = current_val.State
            t = time.localtime()
            ct = time.strftime("%H:%M:%S", t)
            thread.current_values_signal.emit(state,Ewe,I,ct)
            time.sleep(1)
            if thread.isInterruptionRequested():
                print("Interrupted by InterruptionRequested")
                break

        thread.stop()
        thread.finished_signal.emit()


def update_positions_function(electro, thread):
    controller_ser = electro.ser
    #send_command(controller_ser, "0 setout")
    while thread._is_running:
        
        try:
            with electro.write_lock:
                send_command(controller_ser, "pos")
        except serial.SerialTimeoutException as ex:
            print("restart pos thread")
            thread.requestInterruption()
            electro.start_position_thread(update_positions_function)
        
        """t = time.localtime()
        ct = time.strftime("%H:%M:%S", t)
        print(f"ct : {ct}")"""
        #start_time = time.perf_counter()
        
        #send_command(controller_ser, "2 setout")
        #start_time = time.time()
        with electro.read_lock:
            response = read_response(controller_ser)
        #end_time = time.time()
        #send_command(controller_ser, "0 setout")
        
        #end_time = time.perf_counter()
        
        x,y,z = extract_coordinates(response) 
        
        #print(response)
        
        t = time.localtime() # both lines about 1s
        ct = time.strftime("%H:%M:%S", t)  # both lines about 1s
        
        #print(f"ct : {ct}")
        """t = time.localtime()
        ct = time.strftime("%H:%M:%S", t)"""
        #
        
        thread.position_values_signal.emit(x,y,z,ct)
        
        
        if thread.isInterruptionRequested():
            print("Interrupted by InterruptionRequested")
            break
        
        
        #elapse_time = end_time - start_time
        #print("start time: ", start_time)
        #print("End time: ", end_time)
        #print("Elapsed time: ", elapse_time)

        #time.sleep(0.01)

        



#def send_command(ser, command):
#    """
#    Send a command to the Corvus controller.
#    
#    :param ser: Serial object
#    :param command: Command string to send
#    """
#    with self.write_lock:
#        ser.write(f"{command}\r\n".encode())
#    #time.sleep(0.1)  # Wait for the command to be processed
    
#def read_response(ser):
#    """
#   Read the response from the Corvus controller.
#    
#    :param ser: Serial object
#    :return: Response string
#    """
#    with self.read_lock:
#        response = ser.readline().decode().strip()
#    
#    
#    return response
    
def extract_coordinates(response):
    # Find the position of '#6'
    pos_x = response.find("X:")
    pos_y = response.find("Y:")
    pos_z = response.find("Z:")
    # Find the end marker (e.g., "[ 4]:", "[ 5]:", etc.)
    end_pos = response.find("[", pos_z)
    end_pos = response.find("]:", end_pos) + 2

    if pos_x != -1 and pos_y != -1 and pos_z != -1 and end_pos != -1:
        x_str = response[pos_x + 2:pos_y].strip()
        y_str = response[pos_y + 2:pos_z].strip()
        z_str = response[pos_z + 2:end_pos - 2].strip()
        x_new = x_str.split('\x1b')[0].strip()
        y_new = y_str.split('\x1b')[0].strip()
        z_new = z_str.split('\x1b')[0].strip()
        x = float(x_new)
        y = float(y_new)
        z = float(z_new)
        
        return x, y, z
    else:
        raise ValueError("Unable to extract coordinates from the response.")

def main():
    app = QApplication(sys.argv)
    window = ElectroChemistryApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
