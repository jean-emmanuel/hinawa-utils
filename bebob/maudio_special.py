#!/usr/bin/env python3

from bebob.bebob_unit import BebobUnit

from ta1394.general import AvcGeneral
from ta1394.general import AvcConnection
from ta1394.ccm import AvcCcm
from ta1394.audio import AvcAudio

from array import array
from math import log10

class MaudioSpecial(BebobUnit):
    BASE_ADDR = 0xffc700700000
    METER_ADDR = 0xffc700600000
    _ids = {
        0x010071: (0, "Firewire 1814"),
        0x010091: (1, "ProjectMix I/O"),
    }

    input_labels = (
        'stream-1/2', 'stream-3/4',
        'analog-1/2', 'analog-3/4', 'analog-5/6', 'analog-7/8',
        'spdif-1/2', 'adat-1/2', 'adat-3/4', 'adat-5/6', 'adat-7/8',
    )

    output_labels = ('analog-1/2', 'analog-3/4')

    headphone_labels = ('headphone-1/2', 'headphone-3/4')

    mixer_labels = ('mixer-1/2', 'mixer-3/4')

    metering_labels = (
        'analog-in-1', 'analog-in-2', 'analog-in-3', 'analog-in-4',
        'analog-in-5', 'analog-in-6', 'analog-in-7', 'analog-in-8',
        'spdif-in-1', 'spdif-in-2',
        'adat-in-1', 'adat-in-2', 'adat-in-3', 'adat-in-4',
        'adat-in-5', 'adat-in-6', 'adat-in-7', 'adat-in-8',
        'analog-out-1', 'analog-out-2',
        'analog-out-3', 'analog-out-4',
        'spdif-out-1', 'spdif-out-2',
        'adat-out-1', 'adat-out-2', 'adat-out-3', 'adat-out-4',
        'adat-out-5', 'adat-out-6', 'adat-out-7', 'adat-out-8',
        'headphone-out-1', 'headphone-out-2',
        'headphone-out-3', 'headphone-out-4',
        'aux-out-1', 'aux-out-2')

    # LR balance: 0x40-60
    # Write 32 bit, upper 16bit for left channel and lower 16bit for right.
    # The value is between 0x800(L) to 0x7FFE(R) as the same as '10.3.3 LR
    # Balance Control' in 'AV/C Audio Subunit Specification 1.0 (1394TA
    # 1999008)'.

    def __init__(self, path):
        super().__init__(path)
        model_id = -1
        for quad in self.get_config_rom():
            if quad >> 24 == 0x17:
                model_id = quad & 0x00ffffff
                self._id = self._ids[model_id][0]
                info = AvcGeneral.get_unit_info(self.fcp)
                self._company_ids = info['company-id']
        if model_id < 0:
            raise OSError('Not supported')
        # Read transactions are not allowed.
        # TODO: file cache
        self._cache = [
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x00000000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x7FFE8000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x80008000,
            0x00000000,
            0x00000009,
            0x00010001,
            0x00000000]
        self._write_status(0, self._cache)

    # Helper functions
    def _get_array(self):
        arr = array('L')
        if arr.itemsize is not 4:
            arr = array('I')
            if arr.itemsize is not 4:
                raise RuntimeError('Platform has no representation \
                                    equivalent to quadlet.')
        return arr
    def _write_status(self, offset, data):
        self.write_transact(self.BASE_ADDR + offset, data)
    def _read_status(self, offset, quads):
        return self.read_transact(self.BASE_ADDR + offset, quads)

    def _set_volume(self, index, ch, value):
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        if ch == 0:
            datum = (self._cache[index] & 0x0000ffff) | (value << 8)
        else:
            datum = (self._cache[index] & 0xffff0000)| value
        data = self._get_array()
        data.append(datum)
        offset = index * 4
        self._write_status(offset, data)
        self._cache[index] = datum
    def _get_volume(self, index, ch):
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        datum = self._cache[index]
        if ch == 0:
            return datum >> 16
        else:
            return datum & 0x0000ffff

    def set_input_volume(self, target, ch, value):
        if target not in self.input_labels:
            raise ValueError('invalid argument for input stereo pair')
        index = self.input_labels.index(target)
        if index > 7:
            index = index + 8
        self._set_volume(index, ch, value)
    def get_input_volume(self, target, ch):
        if target not in self.input_labels:
            raise ValueError('invalid argument for input stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = self.input_labels.index(target)
        if index > 7:
            index = index + 8
        return self._get_volume(index, ch)

    def set_output_volume(self, target, ch, value):
        if target not in self.output_labels:
            raise ValueError('invalid argument for output stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = self.input_labels.index(target)
        self._set_volume(index, ch, value)
    def get_output_volume(self, target, ch):
        if target not in self.output_labels:
            raise ValueError('invalid argument for output stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = self.input_labels.index(target)
        return self._get_volume(index, ch)

    def set_aux_volume(self, ch, value):
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = 13
        self._set_volume(index, ch, value)
    def get_aux_volume(self, ch):
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = 13
        return self._get_volume(index, ch)

    def set_headphone_volume(self, target, ch, value):
        if target not in self.headphone_labels:
            raise ValueError('invalid argument for heaphone stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = 14 + self.headphone_labels.index(target)
        self._set_volume(index, ch, value)
    def get_headphone_volume(self, target, ch):
        if target not in self.headphone_labels:
            raise ValueError('invalid argument for heaphone stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = 14 + self.headphone_labels.index(target)
        return self._get_volume(index, ch)

    def set_aux_input(self, target, ch, value):
        if target not in self.input_labels:
            raise ValueError('Invalid argument for input stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = 26 + self.input_labels.index(target)
        self._set_volume(index, ch, value)
    def get_aux_input(self, target, ch):
        if target not in self.input_labels:
            raise ValueError('Invalid argument for input stereo pair')
        if ch > 1:
            raise ValueError('Invalid argument for stereo pair channel')
        index = 26 + self.input_labels.index(target)
        return self._get_volume(index, ch)

    def _calculate_mixer_bit(self, mixer, source):
        if source.find('stream') == 0:
            pos = 0
            if source == 'stream-1/2':
                pos = 2
            if self.mixer_labels.index(mixer) == 0:
                pos += 1
        else:
            if source.find('analog') == 0:
                pos = self.mixer_labels.index(mixer) * 4
                pos = pos + self.input_labels.index(source) - 2
            else:
                pos = 16 + (self.input_labels.index(source) - 6) * 2
                pos = pos + self.mixer_labels.index(mixer)
        return pos
    def set_mixer_routing(self, mixer, source, value):
        if mixer not in self.mixer_labels:
            raise ValueError('invalid argument for mixer stereo pair')
        if source not in self.input_labels:
            raise ValueError('Invalid argument for source stereo pair')
        pos = self._calculate_mixer_bit(mixer, source)
        if source.find('stream') == 0:
            index = 37
        else:
            index = 36
        datum = self._cache[index]
        if value > 0:
            datum = datum | (1 << pos)
        else:
            datum = datum & ~(1 << pos)
        print('{0:08x}'.format(datum))
    def get_mixer_routing(self, mixer, source):
        if mixer not in self.mixer_labels:
            raise ValueError('invalid argument for mixer stereo pair')
        if source not in self.input_labels:
            raise ValueError('Invalid argument for source stereo pair')
        pos = self._calculate_mixer_bit(mixer, source)
        if source.find('stream') == 0:
            index = 37
        else:
            index = 36
        datum = self._cache[index]
        return (datum & (1 << pos)) > 0

    # 0x0000ffff - 0x7fffffff
    # db = 20 * log10(vol / 0x80000000)
    # vol = 0, then db = -144.0
    # may differs analog-in and the others.
    def get_meters(self):
        meters = {}
        data = self.read_transact(self.METER_ADDR, 21)
        for i, label in enumerate(self.metering_labels):
            if i % 2:
                meters[self.metering_labels[i]] = data[1 + i // 2] >> 16
            else:
                meters[self.metering_labels[i]] = data[1 + i // 2] & 0x0000ffff
            misc = data[0]
            meters['switch-0'] = (data[0] >> 24) & 0xff
            meters['rotery-0'] = (data[0] >> 16) & 0xff
            meters['rotery-1'] = (data[0] >>  8) & 0xff
            meters['rotery-2'] = (data[0] >>  0) & 0xff
            meters['rate'] = \
                            AvcConnection.sampling_rates[(data[-1] >> 8) & 0x0f]
            meters['sync'] = (data[-1] & 0x0f) > 0
        return meters
