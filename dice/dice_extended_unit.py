from threading import Timer

import gi
gi.require_version('Hinawa', '2.0')
from gi.repository import Hinawa

from dice.dice_unit import DiceUnit

from dice.tcat_protocol_extension import ExtCtlSpace, ExtCapsSpace, ExtCmdSpace, ExtMixerSpace, ExtNewRouterSpace, ExtPeakSpace, ExtCurrentConfigSpace, ExtStandaloneSpace

from dice.tcat_tcd22xx_spec import TcatTcd22xxSpec
from dice.maudio_profire_spec import MaudioProfireSpec
from dice.focusrite_saffirepro_spec import FocusriteSaffireproSpec

__all__ = ['DiceExtendedUnit']

class DiceExtendedUnit(DiceUnit):
    _RATE_MODES = {
        'low':      (32000, 48000),
        'middle':   (88200, 96000),
        'high':     (176400, 192000),
    }

    _SPECS = (
        MaudioProfireSpec,
        FocusriteSaffireproSpec,
    )

    def __init__(self, fullpath):
        super().__init__(fullpath)

        req = Hinawa.FwReq()
        ExtCtlSpace.detect_layout(self._protocol, req)
        ExtCapsSpace.detect_caps(self._protocol, req)

        id_pair = (self.vendor_id, self.model_id)
        for spec in self._SPECS:
            if spec and id_pair in spec.MODELS:
                index = spec.MODELS.index(id_pair)
                break
        else:
            spec = TcatTcd22xxSpec
            index = 0
        self._spec = spec(index)

        # Cache current format of packets in data stream.
        self._cache_router_nodes()
        self.connect('notified', self._handle_notification)

    def _get_rate_mode(self, rate):
        for mode, rates in self._RATE_MODES.items():
            if rates[0] <= rate and rate <= rates[1]:
                return mode
        else:
            raise ValueError('Invalid argument for sampling rate.')

    def _handle_notification(self, obj, message):
        # MEMO: don't stop event loop.
        Timer(0, self._cache_router_nodes)

    def _cache_router_nodes(self):
        req = Hinawa.FwReq()

        rate = self._protocol.read_sampling_rate(req)
        mode = self._get_rate_mode(rate)

        entries = \
            ExtCurrentConfigSpace.read_router_config(self._protocol, req, mode)
        srcs, dsts = self._spec.get_available_ports(self._protocol, req, mode)

        routes = self._spec.normalize_router_entries(self._protocol, entries,
                                                     srcs, dsts)

        ## MEMO: if registered entries are not generated by this module, update
        ## them. Not friendly to the other programs while these entries are
        ## valid for the programs.
        if entries != routes:
            ExtNewRouterSpace.set_entries(self._protocol, req, routes)
            ExtCmdSpace.initiate(self._protocol, req, 'load-from-router', mode)

        self._srcs = srcs
        self._dsts = dsts
        self._routes = routes

    def get_caps(self, category):
        if category not in self._protocol._ext_caps:
            raise ValueError('Invalid argument for capabilities.')
        return self._protocol._ext_caps[category]

    def get_stream_params(self, rate):
        if rate not in self._protocol.get_supported_sampling_rates():
            raise ValueError('Invalid argument for sampling rate.')
        mode = self._get_rate_mode(rate)
        req = Hinawa.FwReq()
        return ExtCurrentConfigSpace.read_stream_config(self._protocol, req, mode)

    def get_router_entries(self, rate):
        if rate not in self._protocol.get_supported_sampling_rates():
            raise ValueError('Invalid argument for sampling rate.')
        mode = self._get_rate_mode(rate)
        entries = []
        req = Hinawa.FwReq()
        routes = ExtCurrentConfigSpace.read_router_config(self._protocol, req,
                                                          mode)
        for route in routes:
            for src in self._srcs:
                if route['src-blk'] == src[1] and route['src-ch'] in src[2]:
                    break
            else:
                continue
            for dst in self._dsts:
                if route['dst-blk'] == dst[1] and route['dst-ch'] in dst[2]:
                    break
            else:
                continue
            entry = {
                'src': '{0}:{1}'.format(src[0], src[2].index(route['src-ch'])),
                'dst': '{0}:{1}'.format(dst[0], dst[2].index(route['dst-ch'])),
            }
            entries.append(entry)
        return entries

    def store_to_storage(self):
        if not self._protocol._ext_caps['general']['storage-available']:
            raise RuntimeError('This feature is not supported.')

        categories = []
        if self._protocol._ext_caps['general']['storable-stream-conf']:
            categories.append('stream-config')
        if self._protocol._ext_caps['mixer']['is-storable']:
            categories.append('mixer')
        if self._protocol._ext_caps['router']['is-storable']:
            categories.append('router')
        if len(categories) == 0:
            raise RuntimeError('Nothing can be stored.')

        req = Hinawa.FwReq()
        rate = self._protocol.read_sampling_rate(req)
        mode = self._get_rate_mode(rate)
        ExtCmdSpace(self._protocol, req, 'load-to-storage', mode)

        # MEMO: however, in most models, configuration of router is stored by
        # 'load-from-router' command.
        return categories

    def load_from_storage(self):
        if not self._protocol._ext_caps['general']['storage-available']:
            raise RuntimeError('This feature is not supported.')

        categories = []
        if self._protocol._ext_caps['general']['storable-stream-conf']:
            categories.append('stream-config')
        if self._protocol._ext_caps['mixer']['is-storable']:
            categories.append('mixer')
        if self._protocol._ext_caps['router']['is-storable']:
            categories.append('router')
        if len(categories) == 0:
            raise RuntimeError('Nothing can be loaded.')

        req = Hinawa.FwReq()
        rate = self._protocol.read_sampling_rate(req)
        mode = self._get_rate_mode(rate)
        ExtCmdSpace.initiate(self._protocol, req, 'load-from-storage', mode)
        # MEMO: I expect notification here.
        return categories

    def _find_route_pairs(self, target):
        for dst in self._dsts:
            if target == dst[0]:
                break
        else:
            raise ValueError('Invalid argument for destination.')

        pairs = []
        for route in self._routes:
            if route['dst-blk'] == dst[1] and route['dst-ch'] in dst[2]:
                pairs.append(route)

        return sorted(pairs, key=lambda pair: (pair['src-ch'], pair['dst-ch']))

    def _set_target_source(self, target, source):
        pairs = self._find_route_pairs(target)

        if source == 'None':
            indices = []
            for pair in pairs:
                indices.append(self._routes.index(pair))
            # Pop backwards.
            indices.sort(reverse=True)
            for index in indices:
                self._routes.pop(index)
        else:
            for dst in self._dsts:
                if target == dst[0]:
                    break
            for src in self._srcs:
                if source == src[0]:
                    break

            if len(pairs) > 0:
                # Left->Left, Right->Right.
                for i, pair in enumerate(pairs):
                    pair['src-blk'] = src[1]
                    pair['src-ch'] = src[2][i]
            else:
                for i in range(2):
                    pair = {
                        'src-blk':  src[1],
                        'src-ch':   src[2][i],
                        'dst-blk':  dst[1],
                        'dst-ch':   dst[2][i],
                        'peak':     0,
                    }
                    self._routes.append(pair)

        req = Hinawa.FwReq()
        rate = self._protocol.read_sampling_rate(req)
        mode = self._get_rate_mode(rate)
        ExtNewRouterSpace.set_entries(self._protocol, req, self._routes)
        ExtCmdSpace.initiate(self._protocol, req, 'load-from-router', mode)

    def _get_target_source(self, target):
        pairs = self._find_route_pairs(target)

        for pair in pairs:
            for src in self._srcs:
                if pair['src-blk'] == src[1] and pair['src-ch'] in src[2]:
                    return src[0]
        return 'None'

    def get_output_labels(self):
        labels = []
        for dst in self._dsts:
            if dst[1] not in ('mixer-tx0', 'mixer-tx1', 'avs0', 'avs1'):
                labels.append(dst[0])
        return labels
    def get_output_source_labels(self):
        labels = ['None']
        for src in self._srcs:
            labels.append(src[0])
        return labels
    def set_output_source(self, target, source):
        if target not in self.get_output_labels():
            raise ValueError('Invalid argument for output pair.')
        if source not in self.get_output_source_labels():
            raise ValueError('Invalid argument for output source pair.')
        self._set_target_source(target, source)
    def get_output_source(self, target):
        if target not in self.get_output_labels():
            raise ValueError('Invalid argument for output pair.')
        return self._get_target_source(target)

    def get_tx_stream_labels(self):
        labels = []
        for dst in self._dsts:
            if dst[1] in ('avs0', 'avs1'):
                labels.append(dst[0])
        return labels
    def get_tx_stream_source_labels(self):
        labels = ['None']
        for src in self._srcs:
            labels.append(src[0])
        return labels
    def set_tx_stream_source(self, target, source):
        if target not in self.get_tx_stream_labels():
            raise ValueError('Invalid argument for tx stream.')
        if source not in self.get_tx_stream_source_labels():
            raise ValueError('Invalid argument for source of tx stream.')
        self._set_target_source(target, source)
    def get_tx_stream_source(self, target):
        if target not in self.get_tx_stream_labels():
            raise ValueError('Invalid argument for tx stream.')
        return self._get_target_source(target)

    def get_mixer_output_labels(self):
        labels = []
        for src in self._srcs:
            if src[1] == 'mixer':
                labels.append(src[0])
        return labels
    def get_mixer_input_labels(self):
        labels = []
        for dst in self._dsts:
            if dst[1] in ('mixer-tx0', 'mixer-tx1'):
                labels.append(dst[0])
        return labels
    def get_mixer_source_labels(self):
        labels = ['None']
        for src in self._srcs:
            if src[1] != 'mixer':
                labels.append(src[0])
        return labels

    def set_mixer_source(self, target, source):
        if target not in self.get_mixer_input_labels():
            raise ValueError('Invalid argument for mixer pair.')
        if source not in self.get_mixer_source_labels():
            raise ValueError('Invalid argument for mixer source pair.')
        self._set_target_source(target, source)
    def get_mixer_source(self, target):
        if target not in self.get_mixer_input_labels():
            raise ValueError('Invalid argument for mixer pair.')
        return self._get_target_source(target)

    def _get_mixer_gains(self, req, output, input):
        if self.get_mixer_source(input) == 'None':
            raise ValueError('This input to mixer has no source.')
        outputs = self.get_mixer_output_labels()
        inputs = self.get_mixer_input_labels()
        if output not in self.get_mixer_output_labels():
            raise ValueError('Invalid argument for mixer stereo pair.')
        if input not in self.get_mixer_input_labels():
            raise ValueError('Invalid argument for mixer input stereo pair.')

        for dst in self._dsts:
            if dst[0] == output:
                break
        for src in self._srcs:
            if src[0] == input:
                break

        gains = []
        for dst_ch in dst[2]:
            for src_ch in src[2]:
                val = ExtMixerSpace.read_gain(self._protocol, req, dst_ch, src_ch)
                gain = {
                    'dst-ch':   dst_ch,
                    'src-ch':   src_ch,
                    'val':      val,
                }
                gains.append(gain)

        return gains

    # TODO: handle some exceptional cases such that both values are zero.
    def set_mixer_gain(self, output, input, ch, db):
        req = Hinawa.FwReq()
        gains = self._get_mixer_gains(req, output, input)
        left = gains[ch]['val']
        right = gains[ch + 2]['val']
        total = left + right
        val = ExtMixerSpace.build_val_from_db(db)
        if total == 0:
            if ch == 0:
                left = val
            else:
                right = val
        else:
            left = int(val * left / total)
            right = int(val * right / total)
        gains[ch]['val'] = left
        gains[ch + 2]['val'] = right
        for gain in gains:
            dst_ch = gain['dst-ch']
            src_ch = gain['src-ch']
            val = gain['val']
            ExtMixerSpace.write_gain(self._protocol, req, dst_ch, src_ch, val)
    def get_mixer_gain(self, output, input, ch):
        req = Hinawa.FwReq()
        gains = self._get_mixer_gains(req, output, input)
        left = gains[ch]['val']
        right = gains[ch + 2]['val']
        return ExtMixerSpace.parse_val_to_db(left + right)

    # TODO: handle some exceptional cases such that both values are zero.
    def set_mixer_balance(self, output, input, ch, balance):
        req = Hinawa.FwReq()
        gains = self._get_mixer_gains(req, output, input)
        left = gains[ch]['val']
        right = gains[ch + 2]['val']
        total = left + right
        if balance == 100.0:
            left = 0
            right = total
        elif balance == 0.0:
            left = total
            right = 0
        else:
            balance /= 100
            left = int(total / (100 - balance) / 100)
            right = int(total / balance / 100)
        gains[ch]['val'] = left
        gains[ch + 2]['val'] = right
        for gain in gains:
            dst_ch = gain['dst-ch']
            src_ch = gain['src-ch']
            val = gain['val']
            ExtMixerSpace.write_gain(self._protocol, req, dst_ch, src_ch, val)
    def get_mixer_balance(self, output, input, ch):
        req = Hinawa.FwReq()
        gains = self._get_mixer_gains(req, output, input)
        left = gains[ch]['val']
        right = gains[ch + 2]['val']
        total = left + right
        if total == 0:
            return float('-inf')
        else:
            return 100 * right / total

    def get_mixer_saturations(self):
        outputs = self.get_mixer_output_labels()

        req = Hinawa.FwReq()
        rate = self._protocol.read_sampling_rate(req)
        mode = self._get_rate_mode(rate)
        saturations = ExtMixerSpace.read_saturation(self._protocol, req, mode)

        mixer_saturations = {}
        for i, saturation in enumerate(saturations):
            index = i // 2
            label = outputs[index]
            if label not in mixer_saturations:
                mixer_saturations[label] = [False, False]
            mixer_saturations[label][i % 2] = saturation
        return mixer_saturations

    def get_metering(self):
        meters = {}

        req = Hinawa.FwReq()
        for peak in ExtPeakSpace.get(self._protocol, req):
            for src in self._srcs:
                if peak['src-blk'] == src[1] and peak['src-ch'] in src[2]:
                    break
            else:
                continue
            for dst in self._dsts:
                if peak['dst-blk'] == dst[1] and peak['dst-ch'] in dst[2]:
                    break
            else:
                continue

            src_index = src[2].index(peak['src-ch'])
            dst_index = dst[2].index(peak['dst-ch'])

            if src[0] not in meters:
                meters[src[0]] = {0: {}, 1: {}}
            if dst[0] not in meters[src[0]][src_index]:
                meters[src[0]][src_index][dst[0]] = {0: 0, 1: 0}
            meters[src[0]][src_index][dst[0]][dst_index] = peak['peak']

        return meters

    def set_standalone_clock_source(self, source):
        req = Hinawa.FwReq()
        labels = self._protocol.get_clock_source_names()
        if source not in labels or source == 'Unused':
            raise ValueError('Invalid argument for clock source.')
        alias = self._protocol.CLOCK_BITS[labels.index(source)]
        ExtStandaloneSpace.write_clock_source(self._protocol, req, alias)

    def get_standalone_clock_source(self):
        req = Hinawa.FwReq()
        labels = self._protocol.get_clock_source_names()
        src = ExtStandaloneSpace.read_clock_source(self._protocol, req)
        index = {v: k for k, v in self._protocol.CLOCK_BITS.items()}[src]
        return labels[index]

    def get_standalone_clock_source_param_options(self, source):
        labels = self._protocol.get_clock_source_names()
        if source not in labels or source == 'Unused':
            raise ValueError('Invalid argument for clock source.')
        alias = self._protocol.CLOCK_BITS[labels.index(source)]

        return ExtStandaloneSpace.get_source_param_options(self._protocol, alias)

    def set_standalone_clock_source_params(self, source, params):
        labels = self._protocol.get_clock_source_names()
        if source not in labels or source == 'Unused':
            raise ValueError('Invalid argument for clock source.')
        alias = self._protocol.CLOCK_BITS[labels.index(source)]

        param_options = \
            ExtStandaloneSpace.get_source_param_options(self._protocol, alias)
        for name, options in param_options.items():
            if name not in params:
                raise ValueError('Invalid argument for params.')

        req = Hinawa.FwReq()
        ExtStandaloneSpace.write_clock_source_params(self._protocol, req, alias,
                                                     params)

    def get_standalone_clock_source_params(self, source):
        labels = self._protocol.get_clock_source_names()
        if source not in labels or source == 'Unused':
            raise ValueError('Invalid argument for clock source.')
        alias = self._protocol.CLOCK_BITS[labels.index(source)]

        req = Hinawa.FwReq()
        return ExtStandaloneSpace.read_clock_source_params(self._protocol, req,
                                                           alias)
