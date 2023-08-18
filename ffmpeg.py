import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, NamedTuple, Optional, Union

import pymediainfo
import jsonschema
from box import Box
from pymediainfo import MediaInfo as PyMediaInfo
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn


class StreamInfo(NamedTuple):
    """A container for specific track information from the MediaInfo library

    Attributes:
        codec (str): The CODEC associated with the track
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
    title: Optional[str] = None
    channels: Optional[int] = None


class SourceMap:
    """A map of sources for `ffmpeg` to use for streams

    Attributes:
        source (int): The zero index of the file being used as a source
        stream_type (str, optional): The type of stream denoted by a single character. Defaults to None.
        stream (int, optional): The zero index of the stream in the file to map. Defaults to None.
        optional (bool): Whether the track is ignored if it does not exist. Defaults to False.
    """
    source: int
    specifier: Optional[str]
    stream: Optional[int]
    optional: bool

    def __init__(self, source: int, specifier: str = None, stream: int = None, optional: bool = False) -> None:
        """Initializes the Source object.

        Args:
            source (int): The zero index of the file being used as a source
            specifier (str, optional): The type of stream denoted by a single character. Defaults to None.
            stream (int, optional): The zero index of the stream in the file to map. Defaults to None.
            optional (bool): Whether the track is ignored if it does not exist. Defaults to False.
        """
        self.source = source
        self.specifier = specifier[0].lower() if specifier else None
        self.stream = stream
        self.optional = optional

    @property
    def cli_options(self) -> str:
        """Returns the `ffmpeg` CLI options associated with this source map

        Returns:
            str: The CLI options for the `ffmpeg` source map
        """
        o = [f"{self.source}"]
        if self.specifier:
            o.append(f":{self.specifier}")
        if self.stream is not None:
            o.append(f":{self.stream}")
        if self.optional:
            o.append("?")
        return f"-map {''.join(o)}"


class OutputMap:
    """A map of source outputs for `ffmpeg` to map sources to.

    Attributes:
        specifier (str, optional): The type of stream denoted by a single character. Defaults to None.
        stream (int, optional): The zero indexed stream to use post-source mapping. Defaults to None.
        options (dict): `ffmpeg` options associated with the stream type for processing.
    """
    specifier: Optional[str]
    stream: Optional[int]
    options: dict

    def __init__(
        self, specifier: Optional[str] = None, stream: Optional[int] = None, options: Optional[dict] = None
    ):
        """Initialize an `ffmpeg` output map.

        Args:
            specifier (str, optional): The type of stream denoted by a single character. Defaults to None.
            stream (int, optional): The zero indexed stream to use post-source mapping. Defaults to None.
            options (dict, optional): `ffmpeg` options associated with the stream type for processing. Defaults to None.
        """
        self.specifier = specifier[0].lower() if specifier else None
        self.stream = stream
        if options:
            self.options = options
        else:
            self.options = dict()

    @property
    def cli_options(self):
        """Returns the CLI options associated with the output map.

        Returns:
            str: The CLI options for the `ffmpeg` output map.
        """
        command = ""
        template = list()
        if self.specifier is not None:
            template.append(f"{self.specifier}")
        if self.stream is not None:
            template.append(f"{self.stream}")
        template = ":".join(template)
        for k, v in self.options.items():
            if template:
                has_template = ":"
            else:
                has_template = ""
            if type(v) in [dict, Box]:
                i = ":".join([f"{i}={j}" for i, j in v.items()])
                command += f"-{k}{has_template}{template} {i} "
            else:
                command += f"-{k}{has_template}{template} {v} "
        return command.strip()


class FfmpegMiscSettings:

    overwrite: bool
    progress_bar: bool
    video_info: StreamInfo

    def __init__(self):
        self.overwrite = False
        self.progress_bar = False
        self.video_info = None


class Ffmpeg:
    """The `ffmpeg` class responsible for generating command-line options and running the actual encode.

    Attributes:
        input_files (List[Path]): The source files to use for the encode.
        output_file (Path): The output file for the encode.
        source_maps (List[SourceMap]): All of the source maps for the input files.
        output_maps (List[OutputMap]): The stream maps from the source maps to the output file.
        settings (FfmpegMiscSettings): Miscellaneous `ffmpeg` settings.
    """

    input_files: List[Union[str, Path]]
    output_file: Path
    source_maps: List[SourceMap]
    output_maps: List[OutputMap]
    settings: FfmpegMiscSettings
    __output: Union[str, Path]

    def __init__(self, ffmpeg_path: Path = None):
        """Initialize a new Ffmpeg instance.

        Args:
            ffmpeg_path (Path, optional): The location of the `ffmpeg` binary. Defaults to None.
        """
        if ffmpeg_path:
            self.ffmpeg_path = Path(ffmpeg_path)
        else:
            # TODO: Fix this for Windows
            self.ffmpeg_path = Path(shutil.which("ffmpeg"))
        self.sources = list()
        self.source_maps = list()
        self.output_maps = list()
        self.settings = FfmpegMiscSettings()

    def load_from_file(self, file_path: Union[Path, str]) -> None:
        """Populate all `ffmpeg` options from a JSON file.

        Args:
            file_path (Union[Path, str]): The JSON file to load.
        """
        
        file_path = Path(file_path)
        with file_path.open('r') as f:
            data = Box(json.load(f))
        
        self.load_from_object(data)

    def load_from_object(self, data: Union[Box, dict]) -> None:
        """Populate all `ffmpeg` options from a data object

        Args:
            data (Union[Box, dict]): The data object to load info from.
        """
        schema = Path("schema/ffmpeg.schema.json")
        with schema.open('r') as f:
            schema_data = json.load(f)
            
        try:
            jsonschema.validate(data, schema_data)
        except jsonschema.ValidationError as e:
            print(f"Could not validate the JSON/object data against the schema: {e.message}")
            sys.exit(100)
        
        data = Box(data)
        self.sources = data.sources
        self.output_file = data.output_file
        self.source_maps = [SourceMap(**i) for i in data.source_maps]
        self.output_maps = [OutputMap(**i) for i in data.output_maps]

    def generate_command(self) -> str:
        """Generate the entire `ffmpeg` command to include command-line options.

        Returns:
            str: The entire `ffmpeg` command to run.
        """
        command = list()
        command.append(f'"{self.ffmpeg_path}"')
        if self.settings.overwrite:
            command.append("-y")
        command.extend(["-progress", "pipe:1"])
        [command.append(f'-i "{i}"') for i in self.sources]
        [command.extend(i.cli_options.split()) for i in self.source_maps]
        [command.extend(i.cli_options.split()) for i in self.output_maps]
        command.append(f'"{str(self.output_file.absolute())}"')
        return ' '.join(command)

    def run(self, verbose: bool = False) -> None:
        """Run the `ffmpeg` encode.

        Args:
            verbose (bool, optional): Display progress and additional statistics during the encode. Defaults to False.
        """
        command = shlex.split(self.generate_command())
        if verbose:
            subprocess.run(command)
        else:
            frames = self.settings.video_info.frames
            progress = Progress(
                TextColumn("[#ffff00]»[bold green] encode"),
                BarColumn(
                    bar_width=None,
                ),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                "[green]{task.completed}/{task.total}[/green]",
                "•",
                TimeRemainingColumn(),
            )
            progress.start()
            task = progress.add_task("test")
            progress.update(task, total=frames)
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )

            regex = r"frame=(\s*\d+)"
            while True:
                time.sleep(0.05)
                output = process.stdout.readline()
                if process.poll() is not None:
                    break
                if output:
                    if m := re.search(regex, output.decode()):
                        progress.update(task, completed=int(m.group(1)))
            progress.update(task, completed=frames)
            progress.stop()

    @property
    def output_file(self) -> Path:
        """Return the output file.

        Returns:
            Path: The output file of the `ffmpeg` encode.
        """
        return self.__output

    @output_file.setter
    def output_file(self, path: Union[str, Path]) -> None:
        """Sets the output file for the `ffmpeg` encode.

        Args:
            path (Union[str, Path]): The path to use for the output file.
        """
        self.__output = Path(path)


class MediaInfo:
    """A quick wrapper class for the MediaInfo library to get track information from a given media file.

    Attributes:
        source_file (Path): The source file to get the information of.
        data (PyMediaInfo): The data returned from the parsing of the source file.
    """

    source_file: Path
    data: PyMediaInfo

    def __init__(self, source_file: Union[Path, str]):
        """Initialize an instance of the MediaInfo object.

        Args:
            source_file (Union[Path, str]): The source file to parse track/stream information from.
        """
        self.source_file = Path(source_file)
        self.data = PyMediaInfo.parse(self.source_file)

    @property
    def video_streams(self) -> List[StreamInfo]:
        """Return all video stream information and zero-index the streams.

        Returns:
            List[StreamInfo]: A list of StreamInfo objects.
        """
        return self.process_streams("Video")

    @property
    def audio_streams(self) -> List[StreamInfo]:
        """Return all audio stream information and zero-index the streams.

        Returns:
            List[StreamInfo]: A list of StreamInfo objects.
        """
        return self.process_streams("Audio")

    @property
    def subtitle_streams(self) -> List[StreamInfo]:
        """Return all subtitle stream information and zero-index the streams.

        Returns:
            List[StreamInfo]: A list of StreamInfo objects.
        """
        return self.process_streams("Text")

    @property
    def streams(self) -> List[StreamInfo]:
        """Return all streams information and zero-index the streams.

        Returns:
            List[StreamInfo]: A list of StreamInfo objects.
        """
        return self.process_streams("All")

    def process_streams(self, category: str) -> List[StreamInfo]:
        """Process all the streams and return a list of StreamInfo objects based on the category given.

        Args:
            category (str): The category of stream to return.

        Returns:
            List[StreamInfo]: A list of StreamInfo objects which are zero-indexed.
        """
        if category != "All":
            info = [i for i in self.data.tracks if i.track_type == category]
        else:
            info = [i for i in self.data.tracks if i.track_type not in ["Menu", "General"]]
        temp = list()
        for idx, t in enumerate(info):
            is_forced = True if t.forced == "Yes" else False
            is_default = True if t.forced == "Yes" else False
            temp.append(
                StreamInfo(
                    codec=t.codec_id,
                    stream=idx,
                    language=t.language,
                    bitrate=t.bit_rate,
                    channels=t.channel_s,
                    forced=is_forced,
                    default=is_default,
                    title=t.title,
                    frames=int(t.frame_count) if t.frame_count else None,
                    stream_type=t.track_type,
                )
            )
        return temp

    @property
    def video_streams_raw(self) -> List[pymediainfo.Track]:
        """Return all of the raw video track information from the MediaInfo library.

        Returns:
            List[pymediainfo.Track]: A list of MediaInfo track information from the MediaInfo library.
        """
        return [i for i in self.data.tracks if i.track_type == "Video"]

    @property
    def audio_streams_raw(self) -> List[pymediainfo.Track]:
        """Return all of the raw audio track information from the MediaInfo library.

        Returns:
            List[pymediainfo.Track]: A list of MediaInfo track information from the MediaInfo library.
        """
        return [i for i in self.data.tracks if i.track_type == "Audio"]

    @property
    def subtitle_streams_raw(self) -> List[pymediainfo.Track]:
        """Return all of the raw subtitle track information from the MediaInfo library.

        Returns:
            List[pymediainfo.Track]: A list of MediaInfo track information from the MediaInfo library.
        """
        return [i for i in self.data.tracks if i.track_type == "Text"]


if __name__ == "__main__":
    ff = Ffmpeg(ffmpeg_path="C:/Program Files/Ffmpeg/ffmpeg.exe")
    ff.load_from_file("test.json")
    print(ff.generate_command())
