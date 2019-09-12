from qcodes import VisaInstrument, Instrument, validators as vals
import math
import struct
from datetime import datetime

date_obj = str(datetime.now())[:10]+';'+str(datetime.now())[11:]

class RohdeSchwarz_SMBV100A(VisaInstrument):
    """Driver class for a Rohde&Schwarz SMBV100A vector signal generator""" 
    def __init__(self, name, address, **kwargs):
        super().__init__(name, address, **kwargs)

        # Parameters should be used for quantities and attributes with a single entry. To change a parameter, use parameter_name(new value) and the set_cmd will be sent to the
        # machine with the contents of the brackets replacing the {}. To find out the current value, use parameter_name(). This calls the get_cmd.

        self.add_parameter('output',
                           set_cmd='OUTP {:d}',
                           vals=vals.Numbers(0, 1),
                           docstring="Turn the output on (1) or off (0)",
                           )
        self.add_parameter('RF_Frequency',
                           set_cmd='FREQ {}',
                           docstring='Set the RF frequency of the generator',
                           )
        self.add_parameter('power',
                           set_cmd='POW {}',
                           docstring='Set the power level of the generator')

        self.add_parameter('baseband_state',
                           set_cmd='BB:ARB:STAT {}',
                           vals=vals.Numbers(0, 1),
                           docstring='Turn baseband signal for IQ modulation on and off')

        self.add_parameter('trig_mode',
                           set_cmd='BB:ARB:SEQ {}',
                           docstring='Choose trigger mode from AUTO, RETRigger, A(rmed)AUTo, A(rmed)RETrigger, SINGle')
        
        self.add_parameter('trig_source',
                           set_cmd='BB:ARB:TRIG:SOUR {}',
                           docstring='Choose trigger source from INT or EXT')

        self.add_parameter('GPIB_delim',
                           set_cmd='SYST:COMM:GPIB:LTER {}',
                           docstring='Choose the delimiter for the GPIB, either EOI or STANdard')

        self.add_parameter('clock_source',
                           set_cmd='ROSC:SOUR {}',
                           docstring='Source for reference oscillator, either INTernal or EXTernal')

        self.add_parameter('dir_contents',
                            get_cmd = 'MMEM:CAT? "{}"',
                            docstring = 'Outputs file name, type and size of all files in the given folder')

        self.connect_message()

    def write_full_file(self, target_file, file_data):
        """Creates file containing file_data at address given by target_file, overwriting if file already exists"""
        self.write('BB:ARB:WAV:DATA "{}", #{}{}{}'.format(target_file, len(str(len(file_data))), len(file_data), file_data))
    
    def write_file(self, filename, I_list, Q_list, clock, marker1 = None, marker2 = None):
        """
        Writes a file to the Rohde&Schwarz SMBV100A using the given data.

        filename: the desired filename (including root) where the wave should be stored\n
        I_list: a list of data values between -1 and 1 which will make up a wave to modulate the inphase component of the RF output\n
        Q_list: a list of data values between -1 and 1 which will make up a wave to modulate the quadrature component of the RF output\n
        clock: sample frequency of the wave. Each value in the I_list is a sample and the wave will be at that value for 1/clock seconds\n
        marker1: a list defining the marker 1 output. Each item in the list is of the form "[start_sample]:[level]", where level is either 0 or 1. For example 
        "360:1" would see the marker at level 1 starting from sample 360 until the sample indicated by the next entry in the list. Marker lists do not always 
        have the same length as the RF output, so the length is indicated using the final entry, which is written "[number_of_samples]:[value of final marker]".
        The first start_sample should be 0.\n
        marker2: see marker1
        """
        while len(Q_list)<len(I_list):
            Q_list.append(I_list[len(Q_list)])      # if Q_list shorter than I_list, it is made up to the full length using I value for the same point in the waveform
        if len(Q_list)>len(I_list):
            Q_list = Q_list[:len(I_list)]
        wavelength = int(4*len(I_list)+1)
        rms_offs = 0
        if all(I_list[i] + Q_list[i] == 0 for i in range(len(I_list))) == False:
            rms_offs = -10*math.log10(math.sqrt(sum([(I_list[i]+Q_list[i]/2)**2 for i in range(len(I_list))])/len(I_list)))
        waveform = ''.join(DACl(I_list[i])+DACl(Q_list[i]) for i in range(len(I_list)))
        entries = ["{TYPE: SMU-WV, %s}" %self.checksum(I_list, Q_list), "{CLOCK: %d}" %clock, "{DATE: %s}" %date_obj, 
                   "{LEVEL OFFS: 0.0, 0.0}", "{CRESTFACTOR: %s}" %rms_offs, "{SAMPLES: %d}" %len(I_list)]
        if marker1 != None:
            entries.append("{MARKER LIST 1: %s}" %"; ".join(marker1))
        if marker2 != None:
            entries.append("{MARKER LIST 2: %s}" %"; ".join(marker2))
        entries.append("{WAVEFORM-%s: #%s}" %(wavelength, waveform))
        data = ''.join(entries)
        self.write('BB:ARB:WAV:DATA "{}", #{}{}{}'.format(filename, len(str(len(data))), len(data), data))

    def read_file(self, target_file, tag_name):
        """Returns the contents of the named tag in target_file"""
        self.ask("BB:ARB:WAV:DATA? '{}', '{}'".format(target_file, tag_name))
    
    def dir_contents(self, route):
        """Returns the name, type and size of all files within the specified folder"""
        self.ask('MMEM:CAT? "{}"'.format(route))
    
    def load_file(self, target_file):
        """Instructs R&S to load target_file"""
        self.write('BB:ARB:WAV:SEL "{}"'.format(target_file))

    def delete_file(self, target_file):
        """Deletes target_file. '*.*' targets all files in given/ current directory (since * represents any number of filename characters. ? represents a single arbitrary character)."""
        self.write('MMEM:DEL "{}"'.format(target_file))
    
    def trigger(self):
        """Triggers release of a wave if not on auto mode"""
        self.write('BB:ARB:TRIG:EXEC')
    
    def file_from_data_list(self, target_file, data_list):
        """Writes waveform data to a new file. Data_list should be a list of real numbers from [-1,1]. set_clock method must be used to assign a sample frequency to the wave."""
        scaled_list = [round(32767*element) for element in data_list]
        full_signal = str(hex(sum(element*16**(4*len(scaled_list)-4*index-4) for index, element in enumerate(scaled_list))))
        waveform = bytearray.fromhex(full_signal[2:]).decode('latin-1')
        self.write('MMEM:DATA:UNPR "NVWFM:{}", #{}{}{}'.format(target_file, len(str(len(waveform))), len(waveform), waveform))

    def set_clock(self, filename, frequency):
        """Assigns a sample frequency to given file"""
        self.write('BB:ARB:WAV:CLOC "{}", {}'.format(filename, frequency))

    def checksum(self, I_list, Q_list):
        """Calculates a checksum from a list of integers in the interval [-1,1] according to the R&S algorithm, to be used by the SMBV100A to check the data is uncorrupted."""
        nonhex_list = [[round(32767*entry) if round(32767*entry) >= 0 else 65536 + round(32767*entry) for entry in pair] for pair in zip(I_list, Q_list)]
        hex_list = [[hex(item)[2:].rjust(4, '0') for item in pair] for pair in nonhex_list]
        swap_list = [[item[2:]+item[:2] for item in pair] for pair in hex_list]
        value_list = [int(pair[0]+pair[1], 16) for pair in swap_list]
        result = 0xA50F74FF
        for item in value_list:
            result = result^item
        return result
