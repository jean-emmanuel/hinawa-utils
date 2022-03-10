# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2018 Takashi Sakamoto

from threading import Thread
from struct import unpack

import gi
gi.require_version('GLib', '2.0')
gi.require_version('Hinawa', '3.0')
from gi.repository import GLib, Hinawa

from hinawa_utils.ta1394.general import AvcGeneral, AvcConnection
from hinawa_utils.ta1394.ccm import AvcCcm

from hinawa_utils.bebob.config_rom_parser import BebobConfigRomParser
from hinawa_utils.bebob.extensions import BcoPlugInfo

__all__ = ['BebobUnit']


class BebobUnit(Hinawa.SndUnit):
    REG_INFO = 0xffffc8020000

    def __init__(self, path):
        super().__init__()
        self.open(path)
        if self.get_property('type') != 3:
            raise ValueError('The character device is not for BeBoB unit')

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

        parser = BebobConfigRomParser()
        info = parser.parse_rom(self.get_node().get_config_rom())
        self.vendor_id = info['vendor-id']
        self.model_id = info['model-id']

        self.fcp = Hinawa.FwFcp()
        self.fcp.bind(self.get_node())
        self.firmware_info = self._get_firmware_info()

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

    def _get_firmware_info(self):
        def _get_string_literal(params):
            if 0x00 in params:
                return '00000000'
            return params.decode('US-ASCII')

        def _get_time_literal(params):
            if 0x00 in params:
                return '000000'
            return params.decode('US-ASCII')

        req = Hinawa.FwReq()
        frames = bytearray(104)
        params = req.transaction(self.get_node(),
                    Hinawa.FwTcode.READ_BLOCK_REQUEST, BebobUnit.REG_INFO, 104,
                    frames)

        info = {}
        info['manufacturer'] = _get_string_literal(params[0:8])
        info['protocol-version'] = unpack('<I', params[8:12])[0]
        info['guid'] = (unpack('<Q', params[12:20])[0] << 32) | \
            unpack('<I', params[20:24])[0]
        info['model-id'] = unpack('<I', params[24:28])[0]
        info['model-revision'] = unpack('<I', params[28:32])[0]
        info['software'] = {
            'build-date':   _get_string_literal(params[32:40]),
            'build-time':   _get_time_literal(params[40:46]),
            'id':           unpack('<I', params[48:52])[0],
            'version':      unpack('<I', params[52:56])[0],
            'base-address': unpack('<I', params[56:60])[0],
            'max-size':     unpack('<I', params[60:64])[0],
        }
        info['bootloader'] = {
            'build-date':   _get_string_literal(params[64:72]),
            'build-time':   _get_time_literal(params[72:80]),
        }
        info['debugger'] = {
            'build-date':   _get_string_literal(params[80:88]),
            'build-time':   _get_string_literal(params[88:96]),
            'id':           unpack('<I', params[96:100])[0],
            'version':      unpack('<I', params[100:104])[0],
        }

        return info
