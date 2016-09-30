# -*- coding: utf-8 -*-

#################################################################################################

import logging

import xbmcgui
import xbmcvfs

import clientinfo
import downloadutils
from utils import window, settings

#################################################################################################

log = logging.getLogger("EMBY."+__name__)

#################################################################################################


class PlayUtils(object):

    _force_transcode = False


    def __init__(self, item, transcode=False, server_id=None):

        self.item = item
        self._force_transcode = transcode
        self.server_id = server_id

        self.client_info = clientinfo.ClientInfo()
        self.doutils = downloadutils.DownloadUtils().downloadUrl

        if server_id is None:
            server = window('emby_server.json')
        else:
            server = window('emby_server%s.json' % server_id)

        self.user_id = server['UserId']
        self.server = server['Server']


    def get_playurl(self):
        '''
            New style to retrieve the best playback method based on sending the profile
            to the server. Based on capabilities the correct path is returned, including
            livestreams that need to be opened by the server.
        '''
        try:
            info = self._get_playback_info()

            if info['SupportsDirectPlay']:
                play_method = "DirectPlay"
                playurl = info['Path']

            elif info['SupportsDirectStream']:
                play_method = "DirectStream"
                playurl = self._direct_stream()

            elif info['SupportsTranscoding']:
                play_method = "Transcode"
                playurl = self.server + info['TranscodingUrl']
                if 'LiveStreamId' not in info:
                    playurl = playurl.replace("stream.ts", "master.m3u8")
            else:
                raise KeyError("Invalid playurl")

        except (KeyError, Exception) as error:
            log.error(error)
            return None

        else:
            log.info("getPlayUrl playmethod: %s - playurl: %s", play_method, playurl)
            window('emby_%s.playmethod' % playurl, value=play_method)

            if info['RequiresClosing'] and 'LiveStreamId' in info:
                window('emby_%s.livestreamid' % playurl, value=info['LiveStreamId'])

            return playurl
    
    def _get_playback_info(self):
        # Gets the playback Info for the current item
        url = "{server}/emby/Items/%s/PlaybackInfo?format=json" % self.item['Id']
        body = {   
            'UserId': self.user_id,
            'DeviceProfile': self._get_device_profile(),
            'StartTimeTicks': 0, #TODO
            'AudioStreamIndex': None, #TODO
            'SubtitleStreamIndex': None, #TODO
            'MediaSourceId': None, 
            'LiveStreamId': None 
        }
        info = self.doutils(url, postBody=body, action_type="POST", server_id=self.server_id)
        log.info("getPlaybackInfo: %s", info)

        mediasource = self._get_optimal_mediasource(info['MediaSources'])
        if mediasource and mediasource['RequiresOpening']:
            mediasource = self._get_live_stream(info['PlaySessionId'], mediasource)

        return mediasource

    def _get_optimal_mediasource(self, mediasources):
        '''
        Select the best possible mediasource for playback
        We select the best stream based on a score
        TODO: Incorporate user preferences for best stream selection
        '''
        optimal_version = {}
        biggest_score = 0

        for mediasource in mediasources:
            score = 0

            # Transform filepath to kodi compliant
            if mediasource['Protocol'] == "File":
                mediasource['Path'] = self._get_file_path(mediasource['Path'])

            # The bitrate is an important quality argument so also base our score on that
            score += mediasource.get("Bitrate", 0)

            for stream in mediasource['MediaStreams']:
                if stream['Type'] == "Video" and 'Width' in stream:
                    # Some streams report high bitrate but have no video width
                    # Priority for video with width value
                    # this is especially true for videos in channels, like trailers
                    score += stream['Width']*10000 

            # Always verify if can be directly played
            if self._supports_directplay(mediasource):
                score += 100000000

            # Direct stream also scores well, compared to transcode
            if mediasource['SupportsDirectStream']:
                score += 5000000

            if score >= biggest_score:
                biggest_score = score
                optimal_version = mediasource

        log.info("getOptimalMediaSource: %s", optimal_version)
        return optimal_version

    def _get_live_stream(self, session_id, mediasource):

        url = "{server}/emby/LiveStreams/Open?format=json"
        body = {   
            'UserId': self.user_id,
            'DeviceProfile': self._get_device_profile(),
            'ItemId': self.item['Id'],
            'PlaySessionId': session_id,
            'OpenToken': mediasource['OpenToken'],
            'StartTimeTicks': 0, #TODO
            'AudioStreamIndex': None, #TODO
            'SubtitleStreamIndex': None #TODO
        }
        info = self.doutils(url, postBody=body, action_type="POST", server_id=self.server_id)
        log.info("getLiveStream: %s", info)
        self._supports_direct_play(info['MediaSource']) 

        return info['MediaSource']
            
    def _get_file_path(self, path):

        if 'VideoType' in self.item:
            # Specific format modification
            video_type = self.item['VideoType']

            if video_type == "Dvd":
                path = "%s/VIDEO_TS/VIDEO_TS.IFO" % path
            elif video_type == "BluRay":
                path = "%s/BDMV/index.bdmv" % path

        # Assign network protocol
        if path.startswith('\\\\'):
            path = path.replace("\\\\", "smb://")
            path = path.replace("\\", "/")

        return path

    def _supports_directplay(self, mediasource):
        # Figure out if the path can be directly played
        mediasource['SupportsDirectPlay'] = xbmcvfs.exists(mediasource['Path']) == 1

        if 'Path' in self.item and self.item['Path'].endswith('.strm'):
            # Allow strm loading regardless
            mediasource['SupportsDirectPlay'] = True

        # Force transcode according to settings
        video_track = mediasource['Name']
        h265 = settings('transcodeH265') or 0
        hi10p = settings('transcodeHi10P') == "true"
        profiles = set([x['Profile'] for x in mediasource['MediaStreams'] if 'Profile' in x])    

        if hi10p and "H264" in video_track and "High 10" in profiles:
            self._force_transcode = True

        if int(h265) and any(track in video_track for track in ("HEVC", "H265")):
            # Avoid H265/HEVC depending on the resolution
            video_res = int(video_track.split("P", 1)[0])
            res = {
                '1': 480,
                '2': 720,
                '3': 1080
            }
            log.info("Resolution is: %sP - transcode: %sP or higher", video_res, res[h265])
            if res[h265] <= video_res:
                self._force_transcode = True

        if self._force_transcode: # Unsupported format
            mediasource['SupportsDirectPlay'] = False
            mediasource['SupportsDirectStream'] = False

        return mediasource['SupportsDirectPlay']
    
    def _get_device_profile(self):
        return {
            "Name": "Kodi",

            "MaxStreamingBitrate": self._get_bitrate(),
            "MusicStreamingTranscodingBitrate": 1280000,

            "TimelineOffsetSeconds": 5,
            
            "Identification": {
                "ModelName": "Kodi",
                "Headers": [{
                    "Name": "User-Agent",
                    "Value": "Kodi",
                    "Match": 2
                }]
            },
            
            "TranscodingProfiles": [{
                "Container": "mp3",
                "AudioCodec": "mp3",
                "Type": 0},
              {
                "Container": "ts",
                "AudioCodec": "ac3",
                "VideoCodec": "h264",
                "Type": 1},
              {
                "Container": "jpeg",
                "Type": 2}
            ],
            
            "DirectPlayProfiles": [{
                "Container": "",
                "Type": 0
              },
              {
                "Container": "",
                "Type": 1
              },
              {
                "Container": "",
                "Type": 2
              }
            ],
            
            "ResponseProfiles": [],
            "ContainerProfiles": [],
            "CodecProfiles": [],
            
            "SubtitleProfiles": [
              {
                "Format": "srt",
                "Method": 2
              },
              {
                "Format": "sub",
                "Method": 2
              },
              {
                "Format": "srt",
                "Method": 1
              },
              {
                "Format": "ass",
                "Method": 1,
                "DidlMode": ""
              },
              {
                "Format": "ssa",
                "Method": 1,
                "DidlMode": ""
              },
              {
                "Format": "smi",
                "Method": 1,
                "DidlMode": ""
              },
              {
                "Format": "dvdsub",
                "Method": 1,
                "DidlMode": ""
              },
              {
                "Format": "pgs",
                "Method": 1,
                "DidlMode": ""
              },
              {
                "Format": "pgssub",
                "Method": 1,
                "DidlMode": ""
              },
              {
                "Format": "sub",
                "Method": 1,
                "DidlMode": ""
              }
            ]
        }

    def _get_bitrate(self):
        # get the addon video quality
        bitrate = {
            '0': 664,
            '1': 996,
            '2': 1320,
            '3': 2000,
            '4': 3200,
            '5': 4700,
            '6': 6200,
            '7': 7700,
            '8': 9200,
            '9': 10700,
            '10': 12200,
            '11': 13700,
            '12': 15200,
            '13': 16700,
            '14': 18200,
            '15': 20000,
            '16': 25000,
            '17': 30000,
            '18': 35000,
            '16': 40000,
            '17': 100000,
            '18': 1000000
        }
        # max bit rate supported by server (max signed 32bit integer)
        return bitrate.get(settings('videoBitrate'), 2147483)*1000

    def direct_stream(self):

        if self.item['Type'] == "Audio":
            extensions = ['mp3', 'aac', 'ogg', 'oga', 'webma', 'wma', 'flac']

            if 'Container' in item and item['Container'].lower() in extensions:
                filename = "stream.%s?static=true" % item['Container']
            else:
                filename = "stream.mp3?static=true"

            playurl = "%s/emby/Audio/%s/%s" % (self.server, self.item['Id'], filename)
        else:
            playurl = "%s/emby/Videos/%s/stream?static=true" % (self.server, self.item['Id'])

        return playurl

    '''def audioSubsPref(self, url, listitem):

        dialog = xbmcgui.Dialog()
        # For transcoding only
        # Present the list of audio to select from
        audioStreamsList = {}
        audioStreams = []
        audioStreamsChannelsList = {}
        subtitleStreamsList = {}
        subtitleStreams = ['No subtitles']
        downloadableStreams = []
        selectAudioIndex = ""
        selectSubsIndex = ""
        playurlprefs = "%s" % url

        try:
            mediasources = self.item['MediaSources'][0]
            mediastreams = mediasources['MediaStreams']
        except (TypeError, KeyError, IndexError):
            return

        for stream in mediastreams:
            # Since Emby returns all possible tracks together, have to sort them.
            index = stream['Index']

            if 'Audio' in stream['Type']:
                codec = stream['Codec']
                channelLayout = stream.get('ChannelLayout', "")
               
                try:
                    track = "%s - %s - %s %s" % (index, stream['Language'], codec, channelLayout)
                except:
                    track = "%s - %s %s" % (index, codec, channelLayout)
                
                audioStreamsChannelsList[index] = stream['Channels']
                audioStreamsList[track] = index
                audioStreams.append(track)

            elif 'Subtitle' in stream['Type']:
                try:
                    track = "%s - %s" % (index, stream['Language'])
                except:
                    track = "%s - %s" % (index, stream['Codec'])

                default = stream['IsDefault']
                forced = stream['IsForced']
                downloadable = stream['IsTextSubtitleStream']

                if default:
                    track = "%s - Default" % track
                if forced:
                    track = "%s - Forced" % track
                if downloadable:
                    downloadableStreams.append(index)

                subtitleStreamsList[track] = index
                subtitleStreams.append(track)


        if len(audioStreams) > 1:
            resp = dialog.select(lang(33013), audioStreams)
            if resp > -1:
                # User selected audio
                selected = audioStreams[resp]
                selectAudioIndex = audioStreamsList[selected]
                playurlprefs += "&AudioStreamIndex=%s" % selectAudioIndex
            else: # User backed out of selection
                playurlprefs += "&AudioStreamIndex=%s" % mediasources['DefaultAudioStreamIndex']
        else: # There's only one audiotrack.
            selectAudioIndex = audioStreamsList[audioStreams[0]]
            playurlprefs += "&AudioStreamIndex=%s" % selectAudioIndex

        if len(subtitleStreams) > 1:
            resp = dialog.select(lang(33014), subtitleStreams)
            if resp == 0:
                # User selected no subtitles
                pass
            elif resp > -1:
                # User selected subtitles
                selected = subtitleStreams[resp]
                selectSubsIndex = subtitleStreamsList[selected]

                # Load subtitles in the listitem if downloadable
                if selectSubsIndex in downloadableStreams:

                    itemid = self.item['Id']
                    url = [("%s/Videos/%s/%s/Subtitles/%s/Stream.srt"
                        % (self.server, itemid, itemid, selectSubsIndex))]
                    log.info("Set up subtitles: %s %s" % (selectSubsIndex, url))
                    listitem.setSubtitles(url)
                else:
                    # Burn subtitles
                    playurlprefs += "&SubtitleStreamIndex=%s" % selectSubsIndex

            else: # User backed out of selection
                playurlprefs += "&SubtitleStreamIndex=%s" % mediasources.get('DefaultSubtitleStreamIndex', "")

        # Get number of channels for selected audio track
        audioChannels = audioStreamsChannelsList.get(selectAudioIndex, 0)
        if audioChannels > 2:
            playurlprefs += "&AudioBitrate=384000"
        else:
            playurlprefs += "&AudioBitrate=192000"

        return playurlprefs'''
