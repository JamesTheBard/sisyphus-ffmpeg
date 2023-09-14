import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Union

import box
import jsonschema
from box import Box
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from ffprobe import StreamInfo, Ffprobe


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
    """A quick object to store extra configuration settings with respect to the encode.

    Attributes:
        overwrite (bool): Automatically overwrite the output file if it already exists. Defaults to False.
        progress_bar (bool): Enables the progress bar. Defaults to False.
        video_info (StreamInfo, optional): Used to populate frame information from the video track. Defaults to None.
    """

    overwrite: bool
    progress_bar: bool
    video_info: Optional[StreamInfo]

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
            binary = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
            self.ffmpeg_path = Path(shutil.which(binary))
        self.sources = list()
        self.source_maps = list()
        self.schema_path = Path(os.path.dirname(os.path.abspath(__file__)))
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
        schema = self.schema_path / schema
        with schema.open('r') as f:
            schema_data = json.load(f)

        try:
            jsonschema.validate(data, schema_data)
        except jsonschema.ValidationError as e:
            print(
                f"Could not validate the JSON/object data against the schema: {e.message}")
            sys.exit(100)

        data = Box(data)
        try:
            self.settings.overwrite = data.overwrite
        except box.exceptions.BoxKeyError:
            pass
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
            return

        if not self.settings.video_info and self.settings.progress_bar:
            self.settings.video_info = self.get_primary_video_information()

        if self.settings.progress_bar and self.settings.video_info:
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
            return

        subprocess.call(command, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        
    def get_primary_video_information(self) -> Optional[StreamInfo]:
        """Parse all of the sources maps and return the video stream information if present.

        Returns:
            Optional[StreamInfo]: The StreamInfo object associated with the first video track. Defaults to None.
        """
        if not self.source_maps or not self.sources:
            return None
        
        for source_map in self.source_maps:
            info = Ffprobe(self.sources[source_map.source])
            if not source_map.specifier:
                s: StreamInfo = info.get_streams()[source_map.stream]
                if s.stream_type == "video":
                    return s
                continue
            elif source_map.specifier == "v":
                return info.get_streams("video")[source_map.stream]
        
        return None
                

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


if __name__ == "__main__":
    ff = Ffmpeg(ffmpeg_path="C:/Program Files/Ffmpeg/ffmpeg.exe")
    ff.load_from_file("test.json")
    print(ff.generate_command())
