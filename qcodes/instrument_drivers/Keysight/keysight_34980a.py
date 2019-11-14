import logging
import warnings
import re
from functools import wraps
from .keysight_34980a_submodules import KeysightSubModule
from .keysight_34934a import Keysight34934A
from qcodes import VisaInstrument
from qcodes.utils import validators as vals
from typing import List, Callable, Optional

LOGGER = logging.getLogger()

KEYSIGHT_MODELS = {'34934A': Keysight34934A}


def post_execution_status_poll(func: Callable) -> Callable:
    """
    Generates a decorator that clears the instrument's status registers
    before executing the actual call and reads the status register after the
    function call to determine whether an error occurs.

    Args:
        func: function to wrap
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.clear_status()
        retval = func(self, *args, **kwargs)

        stb = self.get_status()
        if stb:
            warnings.warn(f"Instrument status byte indicates an error occurred "
                          f"(value of STB was: {stb})! Use `get_error` method "
                          f"to poll error message.",
                          stacklevel=2)
        return retval

    return wrapper


class Keysight34980A(VisaInstrument):
    """
    QCodes driver for 34980A switch/measure unit
    """
    def __init__(self, name, address, terminator='\n', **kwargs):
        """
        Create an instance of the instrument.

        Args:
            name (str): Name of the instrument instance
            address (str): Visa-resolvable instrument address.
        """
        super().__init__(name, address, terminator=terminator, **kwargs)

        self._total_slot = 8
        self._system_slots_info_dict: Optional[dict] = None
        self.module = dict.fromkeys(self.system_slots_info.keys())
        self.scan_slots()
        self.connect_message()

    def get_status(self) -> int:
        """
        Queries status register

        Returns:
            0 if there is no error
        """
        msg = super().ask('*ESR?')
        nums = list(map(int, re.findall(r'\d+', msg)))
        return nums[0]

    def get_error(self) -> str:
        """
        Queries error queue

        Returns:
            error message, or '+0,"No error"' if there is no error
        """
        msg = super().ask(':SYST:ERR?')
        return msg

    def clear_status(self) -> None:
        """
        Clears status register and error queue of the instrument.
        """
        super().write('*CLS')

    def reset(self) -> None:
        """
        Performs an instrument reset.
        Does not reset error queue!
        """
        super().write('*RST')

    @post_execution_status_poll
    def ask(self, cmd: str) -> str:
        return super().ask(cmd)

    @post_execution_status_poll
    def write(self, cmd: str) -> None:
        return super().write(cmd)

    def scan_slots(self) -> None:
        """
        Scan the occupied slots and make an object for each switch matrix
        module installed
        """
        for slot in self.system_slots_info.keys():
            module_info = self.system_slots_info[slot]['model']
            for module in KEYSIGHT_MODELS:
                if module in module_info:
                    name = f'slot_{slot}_{module}'
                    sub_mod = KEYSIGHT_MODELS[module](self, name, slot)
                    self.module[slot] = sub_mod
                    self.add_submodule(name, sub_mod)
                    break
            if self.module[slot] is None:
                name = f'slot_{slot}_{module_info}_no_driver'
                sub_mod = KeysightSubModule(self, name, slot)
                self.module[slot] = sub_mod
                self.add_submodule(name, sub_mod)
                logging.warning(f'can not find driver for {module_info}'
                                f'in slot {slot}')

    @property
    def system_slots_info(self):
        if self._system_slots_info_dict is None:
            self._system_slots_info_dict = self._system_slots_info()
        return self._system_slots_info_dict

    def _system_slots_info(self) -> dict:
        """
        the command SYST:CTYP? returns the following:
        Agilent	Technologies,<Model Number>,<Serial Number>,<Firmware Rev>
        where <Model Number> is '0' if there is no module connected to the
        given slot

        Returns:
            a dictionary, with slot numbers as the keys, and model numbers
            the values
        """
        slots_dict = {}
        keys = ['vendor', 'model', 'serial', 'firmware']
        for i in range(1, self._total_slot+1):
            identity = self.ask(f'SYST:CTYP? {i}').strip('"').split(',')
            if identity[1] != '0':
                slots_dict[i] = dict(zip(keys, identity))
        return slots_dict

    def _are_closed(self, channel: str) -> List[bool]:
        """
        to check if a channel is closed/connected

        Args:
            channel (str): example: '(@1203)' for channel between row=2,
                                    column=3 in slot 1
                                    '(@sxxx, sxxx, sxxx)' for multiple channels

        Returns:
            a list of True and/or False
            True if the channel is closed/connected
            False if is open/disconnected.
        """
        messages = self.ask(f'ROUT:CLOSe? {channel}')
        return [bool(int(message)) for message in messages.split(',')]

    def _are_open(self, channel: str) -> List[bool]:
        """
        to check if a channel is open/disconnected

        Args:
            channel (str): example: '(@1203)' for channel between row=2,
                                    column=3 in slot 1
                                    '(@sxxx, sxxx, sxxx)' for multiple channels

        Returns:
            a list of True and/or False
            True if the channel is open/disconnected
            False if is closed/connected.
        """
        messages = self.ask(f'ROUT:OPEN? {channel}')
        return [bool(int(message)) for message in messages.split(',')]

    def _connect_paths(self, channel_list: str) -> None:
        """
        to connect/close the specified channels	on a switch	module.

        Args:
            channel_list: in the format of '(@sxxx, sxxx, sxxx, sxxx)',
                        where sxxx is a 4-digit channel number
        """
        self.write(f"ROUTe:CLOSe {channel_list}")

    def _disconnect_paths(self, channel_list: str) -> None:
        """
        to disconnect/open the specified channels on a switch module.

        Args:
            channel_list: in the format of '(@sxxx, sxxx, sxxx, sxxx)',
                        where sxxx is a 4-digit channel number
        """
        self.write(f"ROUT:OPEN {channel_list}")

    def disconnect_all(self, slot: Optional[int] = None) -> None:
        """
        to open/disconnect all connections on select module

        Args:
            slot (int): slot number, between 1 and 8 (self._total_slot),
                    default value is None, which means all slots
        """
        cmd = 'ROUT:OPEN:ALL'
        if slot is None:
            self.write(cmd)
        else:
            vals.Ints(min_value=1, max_value=self._total_slot).validate(slot)
            self.write(f'ROUT:OPEN:ALL {slot}')
