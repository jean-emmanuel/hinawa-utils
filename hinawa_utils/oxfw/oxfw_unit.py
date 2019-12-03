# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2018 Takashi Sakamoto

from threading import Thread
from struct import unpack
from time import sleep

import gi
gi.require_version('GLib', '2.0')
gi.require_version('Hinawa', '2.0')
from gi.repository import GLib, Hinawa

from hinawa_utils.ta1394.config_rom_parser import Ta1394ConfigRomParser
from hinawa_utils.ta1394.general import AvcConnection
from hinawa_utils.ta1394.streamformat import AvcStreamFormatInfo

__all__ = ['OxfwUnit']


class OxfwUnit(Hinawa.SndUnit):
    def __init__(self, path):
        super().__init__()
        self.open(path)
        if self.get_property('type') != 4:
            raise ValueError('The character device is not for OXFW unit')

        ctx = GLib.MainContext.new()
        self.create_source().attach(ctx)
        self.__unit_dispatcher = GLib.MainLoop.new(ctx, False)
        self.__unit_th = Thread(target=lambda d: d.run(), args=(self.__unit_dispatcher, ))
        self.__unit_th.start()

        node = self.get_node()
        ctx = GLib.MainContext.new()
        node.create_source().attach(ctx)
        self.__node_dispatcher = GLib.MainLoop.new(ctx, False)
        self.__node_th = Thread(target=lambda d: d.run(), args=(self.__node_dispatcher, ))
        self.__node_th.start()

        parser = Ta1394ConfigRomParser()
        info = parser.parse_rom(self.get_node().get_config_rom())
        self.vendor_name = info['vendor-name']
        self.model_name = info['model-name']

        self.fcp = Hinawa.FwFcp()
        self.fcp.bind(self.get_node())

        self.hw_info = self._parse_hardware_info()
        self.supported_sampling_rates = self._parse_supported_sampling_rates()
        self.supported_stream_formats = self._parse_supported_stream_formats()

    def release(self):
        self.fcp.unbind()
        self.__unit_dispatcher.quit()
        self.__node_dispatcher.quit()
        self.__unit_th.join()
        self.__node_th.join()

    def __enter__(self):
        return self

    def __exit__(self, ex_type, ex_value, trace):
        self.release()

    def _parse_hardware_info(self):
        hw_info = {}

        req = Hinawa.FwReq()

        data = req.read(self, 0xfffff0050000, 4)
        hw_info['asic-type'] = 'FW{0:x}'.format(
            unpack('>H', data[0:2])[0] >> 4)
        hw_info['firmware-version'] = '{0}.{1}'.format(data[2], data[3])

        data = req.read(self, 0xfffff0090020, 4)
        hw_info['asic-id'] = data.decode('US-ASCII').rstrip('\0')

        return hw_info

    def _parse_supported_sampling_rates(self):
        sampling_rates = {}
        playback = []
        capture = []
        # Assume that PCM playback is available for all of models.
        for rate in AvcConnection.SAMPLING_RATES:
            if AvcConnection.ask_plug_signal_format(self.fcp, 'input', 0, rate):
                playback.append(rate)
        sleep(0.02)
        # PCM capture is not always available depending on models.
        for rate in AvcConnection.SAMPLING_RATES:
            if AvcConnection.ask_plug_signal_format(self.fcp, 'output', 0, rate):
                capture.append(rate)
        self._playback_only = (len(capture) == 0)
        for rate in AvcConnection.SAMPLING_RATES:
            if rate in playback or rate in capture:
                sampling_rates[rate] = True
        return sampling_rates

    def _parse_supported_stream_formats(self):
        supported_stream_formats = {}
        supported_stream_formats['playback'] = \
            AvcStreamFormatInfo.get_formats(self.fcp, 'input', 0)
        if len(supported_stream_formats['playback']) == 0:
            supported_stream_formats['playback'] = \
                self._assume_supported_stram_formats('input', 0)
            self._assumed = True
        else:
            self._assumed = False
        if not self._playback_only:
            supported_stream_formats['capture'] = \
                AvcStreamFormatInfo.get_formats(self.fcp, 'output', 0)
            if len(supported_stream_formats['capture']) == 0:
                supported_stream_formats['capture'] = \
                    self._assume_supported_stram_formats('output', 0)
        return supported_stream_formats

    def _assume_supported_stram_formats(self, direction, plug):
        assumed_stream_formats = []
        fmt = AvcStreamFormatInfo.get_format(self.fcp, 'input', 0)
        for rate, state in self.supported_sampling_rates.items():
            if state:
                assumed = {
                    'sampling-rate':    rate,
                    'rate-control':     fmt['rate-control'],
                    'formation':        fmt['formation']}
                assumed_stream_formats.append(assumed)
        return assumed_stream_formats

    def set_stream_formats(self, playback, capture):
        if playback not in self.supported_stream_formats['playback']:
            raise ValueError('Invalid argument for playback stream format')
        if capture:
            if self._playback_only:
                raise ValueError('This unit is playback only')
            if capture not in self.supported_stream_formats['capture']:
                raise ValueError('Invalid argument for capture stream format')
            if playback['sampling-rate'] != capture['sampling-rate']:
                raise ValueError(
                    'Sampling rate mis-match between playback and capture')
        if self._assumed:
            rate = playback['sampling-rate']
            AvcConnection.set_plug_signal_format(self.fcp, 'output', 0, rate)
            AvcConnection.set_plug_signal_format(self.fcp, 'input', 0, rate)
        else:
            AvcStreamFormatInfo.set_format(self.fcp, 'input', 0, playback)
            if not self._playback_only:
                AvcStreamFormatInfo.set_format(self.fcp, 'output', 0, capture)

    def get_current_stream_formats(self):
        playback = AvcStreamFormatInfo.get_format(self.fcp, 'input', 0)
        if not self._playback_only:
            capture = AvcStreamFormatInfo.get_format(self.fcp, 'output', 0)
        else:
            capture = None
        return {'playback': playback, 'capture': capture}
