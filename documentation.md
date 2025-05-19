
---

# Scanning Electro-Chemistry Microscope Software Documentation

*Version: 1.0*  
*Last Updated: [Your Date]*

---

## Table of Contents

1. [Introduction](#introduction)
2. [System Architecture](#system-architecture)
3. [Software Modules Overview](#software-modules-overview)
   - 3.1. Macro Interpreter Module
   - 3.2. Main Application & User Interface
   - 3.3. Experimental Technique Modules
4. [Hardware Integration and Communication](#hardware-integration-and-communication)
   - 4.1. Corvus Controller Integration
   - 4.2. EC‑Lab Development Package and Potentiostat Control
5. [User Interface and Operation](#user-interface-and-operation)
6. [Electrochemical Techniques Implemented](#electrochemical-techniques-implemented)
   - 6.1. Cyclic Voltammetry (CV)
   - 6.2. Chrono-Amperometry (CA) and Chrono-Potentiometry (CP)
   - 6.3. Electrochemical Impedance Spectroscopy (PEIS)
   - 6.4. Scanning Modes: SECCM, SECM, and Line Scan
   - 6.5. Approach Curve Measurements
   - 6.6. Advanced Technique Variants
7. [Macro Language and Scripting](#macro-language-and-scripting)
8. [Troubleshooting and Maintenance](#troubleshooting-and-maintenance)
9. [Appendices and References](#appendices-and-references)
   - 9.1. Command Reference from Corvus Manuals
   - 9.2. EC‑Lab Development Package Highlights
10. [Conclusion and Future Work](#conclusion-and-future-work)

---

## 1. Introduction

This documentation describes the full software package for controlling and executing experiments on a scanning electro‑chemistry microscope. The software integrates:
 
- **Control and automation:** A macro interpreter that executes scripted sequences (see *macro_inter.py* citeturn0file0).
- **User interface:** A PyQt-based GUI that allows the operator to configure, start, and monitor experiments (see *electro.py* citeturn0file1).
- **Experimental techniques:** Modules to perform cyclic voltammetry, chrono-amperometry/potentiometry, impedance spectroscopy (PEIS), line scans, and approach curves, as well as specialized scanning techniques such as SECCM and SECM (see *electro_seccm.py* citeturn0file2, *seccm_cv.py* citeturn0file3, *line_scan.py* citeturn0file4, *approach_curve.py* citeturn0file8, etc.).
- **Hardware communication:** Integration with high‑resolution positioning controllers (Corvus series) and potentiostats using the EC‑Lab Development Package (see *EC‑Lab Development Package.pdf* citeturn0file10 and Corvus manuals citeturn0file11, citeturn0file12).

This document is intended both for developers looking to extend or maintain the software and for advanced users needing detailed technical information about the system’s operation.

---

## 2. System Architecture

The scanning electro‑chemistry microscope software is organized in several layers:

- **Hardware Abstraction:**  
  – Serial communications are used to connect with the Corvus positioning controller and potentiostat devices.  
  – Command functions (e.g., `send_command`, `read_response`) encapsulate low‑level communication (see *approach_curve.py* citeturn0file8).

- **Control & Experiment Automation:**  
  – A macro interpreter (implemented in *macro_inter.py* citeturn0file0) allows users to define and run experiment sequences.  
  – Dedicated threads are used for executing experiments and updating motor positions (as seen in *electro.py* citeturn0file1).

- **User Interface:**  
  – Built using PyQt5, the GUI provides controls for hardware connection, parameter input, experiment start/stop, and live data visualization.
  
- **Technique Modules:**  
  – Specific modules are implemented for each experimental technique (CV, CA, CP, PEIS, SECM/SECCM, line scan, etc.). These modules parse user settings, communicate with the hardware using the EC‑Lab API, and record the measurement data (see *electro_tech.py* citeturn0file7, *elcetro_peis.py* citeturn0file9).

- **Data Handling:**  
  – Data are stored in CSV files and plotted in real time via integrated plotting routines. Data merging (e.g., combining motor position data with measurement data) is also performed post‑experiment.

---

## 3. Software Modules Overview

### 3.1. Macro Interpreter Module
- **File:** *macro_inter.py* citeturn0file0  
- **Purpose:** Implements a simple scripting language that allows variable definitions, looping, conditionals, and commands for hardware movements and measurements.  
- **Features:**  
  – Parsing of custom commands (e.g., `MOVE`, `SET_VOLTAGE`, `READ_CURRENT`).  
  – Execution callback for GUI highlighting.  
  – Supports control flow constructs like `LOOP` and `IF`.

### 3.2. Main Application & User Interface
- **File:** *electro.py* citeturn0file1  
- **Purpose:** Serves as the main entry point of the application, managing the GUI, device connections (both controller and potentiostat), and experiment management.  
- **Features:**  
  – Toolbar actions for connecting/disconnecting devices.  
  – Initiation of motor positioning and experimental threads.  
  – Data buffering, live plotting, and file saving.

### 3.3. Experimental Technique Modules
- **Files & Techniques:**  
  – *electro_seccm.py* citeturn0file2, *seccm_cv.py* citeturn0file3, *electro_abs_secm.py* citeturn0file6, and *electro_secm.py* citeturn0file5: Implement scanning electrochemical cell microscopy (SECCM/SECM) experiments.  
  – *line_scan.py* citeturn0file4: Implements line scan experiments along user‑defined trajectories.  
  – *approach_curve.py* citeturn0file8: Controls the approach curve experiments to determine optimal positioning relative to the sample.  
  – *electro_tech.py* citeturn0file7: Contains routines for advanced techniques like tech‑CA and tech‑CP.  
  – *elcetro_peis.py* citeturn0file9: Implements Potentio Electrochemical Impedance Spectroscopy (PEIS) measurements.

Each module parses its respective technique parameters, interfaces with the hardware (via the EC‑Lab API and Corvus commands), and manages the experiment’s data flow.

---

## 4. Hardware Integration and Communication

### 4.1. Corvus Controller Integration
- **Documentation References:**  
  – *Corvus_Venus_eng_2_1.pdf* citeturn0file11 and *Corvus_Manual_EN_2_2.pdf* citeturn0file12  
- **Key Points:**  
  – The positioning controller uses the Venus‑1 command language.  
  – Commands include positioning (`MOVE`, `rmove`), speed control (`speed`, `stopspeed`), and configuration commands (e.g., `setpitch`, `getpitch`).  
  – The manuals provide detailed syntax, parameter ranges, and examples to configure and operate the controller.

### 4.2. EC‑Lab Development Package and Potentiostat Control
- **Documentation Reference:**  
  – *EC‑Lab Development Package.pdf* citeturn0file10  
- **Key Points:**  
  – Provides the DLL and API functions used to communicate with Bio‑Logic instruments.  
  – Supports various electrochemical techniques through technique files (e.g., `cv.ecc`, `ca.ecc`, `peis.ecc`).  
  – Techniques are loaded and executed via API calls (e.g., `BL_LoadTechnique`, `BL_StartChannel`, `BL_GetData`).

---

## 5. User Interface and Operation

The GUI (developed in *electro.py* citeturn0file1) is designed for ease of use:

- **Toolbar and Menus:**  
  – Connect/disconnect controllers and potentiostats.  
  – Select channels and set measurement parameters.
- **Input Panels:**  
  – Parameter entry for each experiment type (CV, CA, CP, etc.).  
  – Macro editor to load or create experiment scripts.
- **Display Panels:**  
  – Real‑time data plots for voltage, current, and impedance measurements.  
  – Log output and status messages.
- **Experiment Control:**  
  – Start, pause, resume, and stop buttons manage experiments.  
  – Data is recorded into CSV files and optionally merged with motor position data.

---

## 6. Electrochemical Techniques Implemented

This section details the core experimental methods integrated into the microscope software.

### General technique Implementation 
These implementations are based on examples from the *EC-Lab development package* as follows:
- **Import** all the necessary libraries 
    ```python
    import kbio.kbio_types as KBIO
    from kbio.c_utils import c_is_64b
    from kbio.kbio_api import KBIO_api
    from kbio.kbio_tech import ECC_parm
    from kbio.kbio_tech import get_experiment_data
    from kbio.kbio_tech import get_info_data
    from kbio.kbio_tech import make_ecc_parm
    from kbio.kbio_tech import make_ecc_parms
    from kbio.utils import exception_brief
    ```
- The experiement block is encampsulated in a dedicated function that takes the *QMainWindow* and *QThread* as arguments. The *QThread* is used to run the experiment in a separate thread than the main one to avoid the User Interface from blocking or other issues.

- **Initialize** hardware parameters by referencing them through the *QMainWindow* instance.
    ```python
    # Test parameters, to be adjusted

        verbosity = 1

        address = "USB0"
        #address = "10.100.19.1"
        channel = electro.potentiostat_channel_selected
        binary_path = "C:/EC-Lab Development Package_v/lib"

        force_load_firmware = True
    ```
- **Set** the techniques file library (*.ecc*) based on the implemented technique. Refer to *ec-lab development packages* user's guide.Techniques for corresponding files.
    ```python
    # CV parameter values
    cv3_tech_file = "the cv.ecc"
    cv4_tech_file = "cv4.ecc"
    cv5_tech_file = "cv5.ecc"
    ```

- **Define** the technique's parameters dictionary following its specification (refer to *ec-lab development packages* user's guide.Techniques).
    ```python
    # Dictionnary of CV parameters
    CV_parms = {
        "vs_init": ECC_parm("vs_initial", bool),
        "voltage_step": ECC_parm("Voltage_step", float),
        "scan_rate": ECC_parm("Scan_Rate", float),
        "scan_number": ECC_parm("Scan_number", int),
        "record_dE": ECC_parm("Record_every_dE", float),
        "avg_over_dE": ECC_parm("Average_over_dE", bool),
        "repeat": ECC_parm("N_Cycles", int),
        "begin_meas_I": ECC_parm("Begin_measuring_I", float),
        "end_meas_I": ECC_parm("End_measuring_I", float),
        "I_range": ECC_parm("I_Range", int),
        "E_range": ECC_parm("E_Range", int),
        "Bandwidth": ECC_parm("Bandwidth", int),
    }
    ```
- **Initialize** some local variables and **Get** values setted/inputed from the *QMainWindow* instance.
    ```python
    # defining a voltage step parameter
    @dataclass
    class voltage_step:
        voltage: float
        vs_init: bool
        scan_rate: float

    Ei = float(electro.cv_options['Ei'])
    E1 = float(electro.cv_options['E1'])
    E2 = float(electro.cv_options['E2'])
    Ef = float(electro.cv_options['Ef'])
    scan_rate = float(electro.cv_options['Scan rate']) # V/s
    scan_number = 2
    record_dE=0.01 # volt
    avg_over_dE=True
    begin_meas_I=0.1
    end_meas_I=1.0
    i_range = "I_RANGE_"+electro.i_range_selector.currentText()
    if electro.e_range_selector.currentText() == '-2.5V, 2.5V':
        e_range =  "E_RANGE_2_5V"
    elif electro.e_range_selector.currentText() == '-5V, 5V':
        e_range =  "E_RANGE_5V"
    elif electro.e_range_selector.currentText() == '-10V, 10V':
        e_range =  "E_RANGE_10V"
    else:
        e_range =  "E_RANGE_AUTO"

    if electro.approach_options['vs_init'] == 'True':
        vs_init_val = True
    elif electro.approach_options['vs_init'] == 'False':
        vs_init_val = False
    
    steps = [
        voltage_step(Ei, False, scan_rate),  # 3V during 2s
        voltage_step(E1,False, scan_rate),  # 3V during 2s
        voltage_step(E2, False, scan_rate),  # 3V during 2s
        #voltage_step(Ei, False, scan_rate),  # 3V during 2s
        voltage_step(Ef,False, scan_rate),  # 3V during 2s
    ]
    max_bound_E = max(Ei, E1, E2, Ef)
    ```

- **Define** some helper functions
    ```python
    # helper functions

    def newline():
        print()


    def print_exception(e):
        print(f"{exception_brief(e, verbosity>=2)}")

    def print_messages(ch):
        """Repeatedly retrieve and print messages for a given channel."""
        while True:
            # BL_GetMessage
            msg = api.GetMessage(id_, ch)
            if not msg:
                break
            print(msg)


    # determine library file according to Python version (32b/64b)
    if c_is_64b:
        DLL_file = "EClib64.dll"
    else:
        DLL_file = "EClib.dll"

    DLL_path = f"{binary_path}{os.sep}{DLL_file}"
    ```

- 


### 6.1. Cyclic Voltammetry (CV)
- **Modules:** *seccm_cv.py* citeturn0file3 and parts of *electro.py*  
- **Parameters:**  
  – Initial, switching, and final potentials, scan rate, number of cycles, and averaging options.
- **Operation:**  
  – The CV routine loads technique files (e.g., `cv.ecc`), communicates with the potentiostat API, and retrieves data in real time.

### 6.2. Chrono-Amperometry (CA) and Chrono-Potentiometry (CP)
- **Modules:** Found in *electro.py* and *electro_tech.py* citeturn0file7  
- **Parameters:**  
  – Voltage or current step, duration, record intervals, and number of cycles.
- **Operation:**  
  – Executed during approach curves or steady-state measurements.

### 6.3. Potentio Electrochemical Impedance Spectroscopy (PEIS)
- **Modules:** *elcetro_peis.py* citeturn0file9  
- **Parameters:**  
  – Frequency range, amplitude voltage, duration per step, averaging, and sweep options.
- **Operation:**  
  – Uses dedicated technique files (e.g., `peis.ecc`) and EC‑Lab API calls to collect impedance data.

### 6.4. Scanning Modes (SECCM and SECM)
- **Modules:** *electro_seccm.py* citeturn0file2, *electro_abs_secm.py* citeturn0file6, *electro_secm.py* citeturn0file5  
- **Parameters:**  
  – Scan grid dimensions, retract height, and technique-specific settings.
- **Operation:**  
  – Combines motor positioning (via Corvus commands) with electrochemical measurement sequences.

### 6.5. Line Scan Experiments
- **Module:** *line_scan.py* citeturn0file4  
- **Parameters:**  
  – Scan length, speed, voltage applied, and estimated scan duration.
- **Operation:**  
  – The system coordinates motor movement along a predefined line while recording electrochemical data.

### 6.6. Approach Curve Measurements
- **Module:** *approach_curve.py* citeturn0file8  
- **Purpose:**  
  – To safely approach the sample surface by monitoring current changes.
- **Operation:**  
  – The routine executes a series of controlled voltage steps while recording the approach response.

---

## 7. Macro Language and Scripting

The macro interpreter (in *macro_inter.py* citeturn0file0) allows users to automate complex experiment sequences.

- **Syntax Overview:**  
  – Variables: `var X` to declare variables.  
  – Commands: e.g., `MOVE(X,Y,Z)`, `SET_VOLTAGE(V)`, `READ_CURRENT VAR`.  
  – Flow Control: `LOOP n ... END_LOOP` and conditional blocks with `IF ... END_IF`.
- **Usage:**  
  – Scripts are loaded via the GUI and executed in a dedicated thread, with line highlighting and pause/resume functionality.
- **Benefits:**  
  – Enables repeatable, automated experiments without manual intervention.

---

## 8. Troubleshooting and Maintenance

### Common Issues and Their Resolutions
- **Hardware Connection:**  
  – Ensure that serial port settings (COM port, baud rate) match the hardware specifications (see *electro.py* citeturn0file1).
- **Firmware Loading:**  
  – Verify that the Corvus controller firmware is loaded (consult *Corvus_Manual_EN_2_2.pdf* citeturn0file12 for troubleshooting firmware issues).
- **Technique Execution:**  
  – Check that the correct technique file (e.g., `cv.ecc`, `ca.ecc`, `peis.ecc`) is selected based on the instrument family and experimental parameters.
- **Macro Execution:**  
  – Syntax errors in macros can halt execution; use the log outputs to identify the problematic line.
- **Data Acquisition:**  
  – Inconsistent data or communication timeouts might be resolved by verifying USB/serial cable connections and proper initialization of the EC‑Lab API.

### Maintenance Guidelines
- **Software Updates:**  
  – Update the code modules in parallel with any hardware firmware updates.
- **Documentation Review:**  
  – Periodically review the EC‑Lab Development Package and Corvus manuals for any changes in communication protocols or new technique parameters.
- **Backup Configurations:**  
  – Save frequently used macros and GUI configuration settings.

---

## 9. Appendices and References

### 9.1. Corvus Command Reference
For detailed information on the command language used to control the positioning system (e.g., `setpitch`, `getvel`, `move`), please refer to:
- *Corvus_Venus_eng_2_1.pdf* citeturn0file11
- *Corvus_Manual_EN_2_2.pdf* citeturn0file12

These documents provide exhaustive command syntax, parameter ranges, examples, and hardware configuration details.

### 9.2. EC‑Lab Development Package Highlights
The EC‑Lab Development Package (see *EC‑Lab Development Package.pdf* citeturn0file10) is key for interfacing with Bio‑Logic instruments. Key topics include:
- Calling conventions and API usage.
- Technique file formats and parameter definitions.
- Data retrieval and conversion routines for various electrochemical techniques.

---

## 10. Conclusion and Future Work

This documentation provides a complete overview of the scanning electro‑chemistry microscope software—from system architecture and individual module functions to hardware integration and user operation. Future improvements may include:
- Enhanced data analysis and visualization capabilities.
- Integration of additional electrochemical techniques.
- More robust error handling and real-time diagnostics.

For further development or support, please consult the detailed manuals and API documentation provided with the hardware.

---

*This documentation draft is intended to be a living document. Please update sections as new features are added or hardware/software configurations change.*

---
