import json
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from box import Box


@dataclass
class StreamInfo:
    """A container for specific track information from the MediaInfo library

    Attributes:
        codec (str): The CODEC associated with the track
        codec_long (str): The long description of the codec
        track (int): The zero-index track value of the media file
        language (str): The two character language code of the track
        bitrate (int, optional): The bitrate of the track. Defaults to None.
        forced (bool): Whether the track is forced
        default (bool): Whether the track is selected by default
        frames (int, optional): The number of frames associated with the track. Defaults to None.
        stream_type (str): The track type associated with the track
        title (str, optional): The title of the track. Defaults to None.
        channels (int, optional): The number of audio channels associated with the track. Defaults to None.
    """
    codec: str
    stream: int
    language: str
    bitrate: Optional[int]
    forced: bool
    default: bool
    frames: Optional[int]
    stream_type: str
    codec_long: str = None
    title: Optional[str] = None
    channels: Optional[int] = None


class Ffprobe:

    ffprobe_path: Path
    media_path: Path

    def __init__(self, media_path: Union[str, Path], ffprobe_path: Union[str, Path] = None, count_frames: bool = False):
        if ffprobe_path:
            self.ffprobe_path = Path(ffprobe_path)
        else:
            binary = "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"
            self.ffprobe_path = Path(shutil.which(binary))
        self.media_path = Path(media_path)
        self.count_frames = count_frames
        self.streams = self.process_media()

    def process_media(self) -> Box:
        command_options = [self.ffprobe_path, "-v",
                           "quiet", "-show_streams", "-print_format", "json"]
        if self.count_frames:
            command_options.append("-count_frames")
        command_options.append(self.media_path)
        output = Box(json.loads(subprocess.check_output(command_options)))

        streams = list()
        for idx, stream in enumerate(output.streams):
            if "bit_rate" in stream.keys():
                bitrate = stream.bit_rate
            elif "tags" in stream.keys():
                bitrate = getattr(stream.tags, "BPS", None)
            else:
                bitrate = None

            if "nb_read_frames" in stream.keys():
                frames = stream.nb_read_frames
            elif "nb_frames" in stream.keys():
                frames = stream.nb_frames
            elif "tags" in stream.keys():
                frames = getattr(stream.tags, "NUMBER_OF_FRAMES", None)
            else:
                frames = None

            streams.append(
                StreamInfo(
                    codec_long=stream.codec_long_name,
                    codec=stream.codec_name,
                    stream=idx,
                    language=stream.tags.language if "tags" in stream.keys() else None,
                    bitrate=int(bitrate) if bitrate else None,
                    forced=bool(stream.disposition.forced),
                    default=bool(stream.disposition.default),
                    frames=int(frames) if frames else None,
                    stream_type=stream.codec_type,
                    title=getattr(stream.tags, "title",
                                  None) if "tags" in stream.keys() else None,
                    channels=getattr(stream, "channels", None),
                )
            )
        return streams

    def get_streams(self, stream_type: str = "all"):
        if stream_type != "all":
            streams = [i for i in self.streams if i.stream_type == stream_type]
        else:
            streams = self.streams

        new_streams = list()
        for idx, stream in enumerate(streams):
            stream.stream = idx
            new_streams.append(stream)
        return new_streams


if __name__ == "__main__":
    a = Ffprobe("test1.mkv")
    [print(f'- {i}') for i in a.get_streams()]
    print()
    [print(f'- {i}') for i in a.get_streams('audio')]
