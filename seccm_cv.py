""" Bio-Logic OEM package python API.

Script shown as an example of how to run an experiment with a Biologic instrument
using the EC-Lab OEM Package library.

The script uses parameters which are provided below.

"""

import os
import sys
import time
from dataclasses import dataclass

import kbio.kbio_types as KBIO
from kbio.c_utils import c_is_64b
from kbio.kbio_api import KBIO_api
from kbio.kbio_tech import ECC_parm
from kbio.kbio_tech import get_experiment_data
from kbio.kbio_tech import get_info_data
from kbio.kbio_tech import make_ecc_parm
from kbio.kbio_tech import make_ecc_parms
from kbio.utils import exception_brief


def perf_cv(electro, thread):
    # ------------------------------------------------------------------------------#

    # Test parameters, to be adjusted

    verbosity = 1

    address = "USB0"
    #address = "10.100.19.1"
    channel = electro.potentiostat_channel_selected

    binary_path = "C:/EC-Lab Development Package_v/lib"

    force_load_firmware = True

    # CV parameter values
    cv3_tech_file = "cv.ecc"
    cv4_tech_file = "cv4.ecc"
    cv5_tech_file = "cv5.ecc"


    vs_init = (False)*5
    voltage_step = 0.0 # volt
    
    record_dE=0.01 # volt
    avg_over_dE=True
    repeat= int(electro.cv_options['N_Cycles'])
    begin_meas_I=0.1
    end_meas_I=1.0
    bandwidth='BW_2'
    scan_number = 2
    i_range = "I_RANGE_"+electro.i_range_selector.currentText()
    if electro.e_range_selector.currentText() == '-2.5V, 2.5V':
        e_range =  "E_RANGE_2_5V"
    elif electro.e_range_selector.currentText() == '-5V, 5V':
        e_range =  "E_RANGE_5V"
    elif electro.e_range_selector.currentText() == '-10V, 10V':
        e_range =  "E_RANGE_10V"
    else:
        e_range =  "E_RANGE_AUTO"

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
        #"E_range": ECC_parm("E_Range", int),
        "Bandwidth": ECC_parm("Bandwidth", int),
    }


    # defining a voltage step parameter
    @dataclass
    class voltage_step:
        voltage: float
        vs_init: bool
        scan_rate: float

    # list of step parameters
    """steps = [
        voltage_step(0.0, True, 5),  # 3V during 2s
        voltage_step(0.6,True, 5),  # 3V during 2s
        voltage_step(-0.2, True, 5),  # 3V during 2s
        voltage_step(0.0, True, 5),  # 3V during 2s
        voltage_step(0.0,True, 5),  # 3V during 2s
    ]"""
    Ei = float(electro.cv_options['Ei'])
    E1 = float(electro.cv_options['E1'])
    E2 = float(electro.cv_options['E2'])
    Ef = float(electro.cv_options['Ef'])
    scan_rate = float(electro.cv_options['Scan rate']) # V/s
    vs_init_value = electro.turn_to_ocv
    if electro.approach_options['vs_init'] == 'True':
        vs_init_val = True
    elif electro.approach_options['vs_init'] == 'False':
        vs_init_val = False
    
    print(f"vs_int = {vs_init_val}")
    steps = [
        voltage_step(Ei, False, scan_rate),  # 3V during 2s
        voltage_step(E1,False, scan_rate),  # 3V during 2s
        voltage_step(E2, False, scan_rate),  # 3V during 2s
        #voltage_step(Ei, False, scan_rate),  # 3V during 2s
        voltage_step(Ef,False, scan_rate),  # 3V during 2s
    ]

    max_bound_E = max(Ei, E1, E2, Ef)


    # ==============================================================================#

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

    # ==============================================================================#


    """

        Example main :

        * open the DLL,
        * connect to the device using its address,
        * retrieve the device channel info,
        * test whether the proper firmware is running,
        * create a CV parameter list (a subset of all possible parameters),
        * load the CV technique into the channel,
        * start the technique,
        * in a loop :
            * retrieve and display experiment data,
            * stop when channel reports it is no longer running

        Note: for each call to the DLL, the base API function is shown in a comment.

        """

    try:
        newline()

        # API initialize
        api = electro.potentiostat_api
        # BL_GetLibVersion
        version = api.GetLibVersion()
        print(f"> EcLib version: {version}")
        newline()

        # BL_Connect
        id_ = electro.potentiostat_id_
        device_info = electro.potentiostat_device_info
        print(f"> device[{address}] info :")
        print(device_info)
        newline()

        # based on board_type, determine firmware filenames
        board_type = electro.potentiostat_board_type
        match board_type:
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
        #print(f"> Loading {firmware_path} ...")
        ## create a map from channel set
        #channel_map = api.channel_map({channel})
        ## BL_LoadFirmware
        #api.LoadFirmware(id_, channel_map, firmware=firmware_path, fpga=fpga_path, force=force_load_firmware)
        #print("> ... firmware loaded")
        newline()

        # BL_GetChannelInfos
        channel_info = api.GetChannelInfo(id_, channel)
        print(f"> Channel {channel} info :")
        print(channel_info)
        newline()

        if not channel_info.is_kernel_loaded:
            print("> kernel must be loaded in order to run the experiment")
            sys.exit(-1)

        # pick the correct ecc file based on the instrument family
        match board_type:
            case KBIO.BOARD_TYPE.ESSENTIAL.value:
                tech_file = cv3_tech_file
            case KBIO.BOARD_TYPE.PREMIUM.value:
                tech_file = cv4_tech_file
            case KBIO.BOARD_TYPE.DIGICORE.value:
                tech_file = cv5_tech_file
            case _:
                print("> Board type detection failed")
                sys.exit(-1)


        # BL_Define<xxx>Parameter
        p_steps = list()
        """p_vs_steps = list()
        p_voltage_steps = list()
        p_scan_rate_steps = list()"""

        for idx, step in enumerate(steps):
            #print(f"idx = {idx}")
            parm = make_ecc_parm(api, CV_parms["vs_init"], step.vs_init, idx)
            p_steps.append(parm)
            parm = make_ecc_parm(api, CV_parms["voltage_step"], step.voltage, idx)
            p_steps.append(parm)
            parm = make_ecc_parm(api, CV_parms["scan_rate"], step.scan_rate, idx)
            p_steps.append(parm)

        """vs_init_list_parms = make_ecc_parms(api, *p_vs_steps)
        voltage_list_parms = make_ecc_parms(api, *p_voltage_steps)
        scan_rate_list_parms = make_ecc_parms(api, *p_scan_rate_steps)"""
        # scan number 
        p_scan_number = make_ecc_parm(api, CV_parms["scan_number"], scan_number)
        #print(">scan number")

        # record parameters
        p_record_dE = make_ecc_parm(api, CV_parms["record_dE"], record_dE)
        p_avg_over_dE = make_ecc_parm(api, CV_parms["avg_over_dE"], avg_over_dE)
        #print(">record afg over dE")
        # repeating factors
        p_repeat = make_ecc_parm(api, CV_parms["repeat"], repeat)

        # measuring end points
        p_begin_meas_I = make_ecc_parm(api, CV_parms["begin_meas_I"], begin_meas_I)
        p_end_meas_I = make_ecc_parm(api, CV_parms["end_meas_I"], end_meas_I)
        p_I_range = make_ecc_parm(api, CV_parms["I_range"], KBIO.I_RANGE[i_range].value)
        #p_erange = make_ecc_parm(api, CV_parms["E_range"], KBIO.E_RANGE[e_range].value)
        p_bandwidth = make_ecc_parm(api, CV_parms["Bandwidth"], KBIO.BANDWIDTH[bandwidth].value)
        #print(">measeuring end points ")


        # make the technique parameter array
        ecc_parms = make_ecc_parms(api, *p_steps, p_scan_number, p_record_dE, p_avg_over_dE, p_repeat, p_begin_meas_I, p_end_meas_I, p_I_range)
        #print(">ecc_parms ")

        # BL_LoadTechnique
        api.LoadTechnique(id_, channel, tech_file, ecc_parms, first=True, last=True, display=(verbosity > 1))
        #print(">LoadTechnique ")
        # BL_StartChannel
        api.StartChannel(id_, channel)
        #print(">StartChannel ")


        # experment loop
        csvfile = open("electro_cv.csv", "w")
        
        csvfile.write("t (s),Ewe (V),I (A),Cycle (N)\n")
        count = 0
        print("> Reading data ", end="", flush=True)
        while thread._is_running:
            # BL_GetData
            data = api.GetData(id_, channel)
            status, tech_name = get_info_data(api, data)
            print(".", end="", flush=True)

            for output in get_experiment_data(api, data, tech_name, board_type):
                # Emit the signal with new data
                t = time.localtime()
                ct = time.strftime("%H:%M:%S", t)
                thread.data_signal.emit(output['Ewe'], output['I'],output['t'],output['cycle'],ct)
                csvfile.write(f"{output['t']},{output['Ewe']},{output['I']},{output['cycle']}\n")
                csvfile.flush()
                count += 1


                if thread.isInterruptionRequested():
                    newline()
                    print("Interrupted by InterruptionRequested")
                    status = "STOP"
                    break

                if max_bound_E < output['Ewe']:
                    status = "STOP"
                    break

            if status == "STOP":
                break

            #time.sleep(1)
        
        thread.stop()
        thread.finished_signal.emit()
        csvfile.close
        print()
        print(f"> {count} data have been writted into cv.csv")
        print("> experiment done")
        newline()

        # BL_Disconnect
        #api.Disconnect(id_)


    except KeyboardInterrupt:
        print(".. interrupted")
    except Exception as e:
        print_exception(e)