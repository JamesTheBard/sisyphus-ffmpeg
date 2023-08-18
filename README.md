# Introduction

The `sisyphus-ffmpeg` Python module is a wrapper around `ffmpeg` that makes stream mapping and options for processing a bit easier to handle.  The module can be used as-is, but it was designed to support the `sisyphus-client` software used for distributed encoding and processing (which would explain the loading of JSON configurations).

## Sample Code

### Pure Pythonic

```python
from ffmpeg import Ffmpeg, SourceMap, OutputMap

# Create the Ffmpeg object
ff = Ffmpeg()

# Add the sources for `ffmpeg` to use
ff.sources = [
    "source_file_1.mkv",
    "source_file_2.ac3",
]

# Define all of the source maps which map a stream from a given
# source (zero-indexed) and a stream that will be ultimately proccessed
# and muxed into the output file.  When using specifiers, the stream
# number is the nth stream of that specifier type in the file.  If
# there's no specifier, it's the nth stream of the file without regard
# to type.
ff.source_maps = [
    SourceMap(source=0, specifier="Video", stream=0),
    SourceMap(source=1, specifier="Audio", stream=0),
    SourceMap(source=0, specifier="Subtitles", stream=0),
]

# Once the source maps are created, each source map is now a stream that
# can be processed via the output map.  The streams are zero-indexed and
# based on the order of the source maps of the previous section.

# Stream 0 is the video from source 0 (the 'mkv' file)
ff.output_maps.append(
    OutputMap(
        stream=0, 
        specifier="Video", 
        options={
            "codec": "libx265",
            "crf": 19,
            "pix_fmt": "yuv420p10le",
            "preset": "slow",
            "x265-params": {
                "limit-sao": 1,
                "bframes": 8,
                "psy-rd": 1,
                "psy-rdoq": 2,
                "aq-mode": 3
            }
        }    
    )
)

# Stream 1 is the audio file from source 1 (the 'ac3' file)
ff.output_maps.append(
    OutputMap(
        stream=1, 
        specifier="Audio", 
        options={
            "codec": "libopus",
            "b": "128k",
            "ac": 2,
            "vbr": "on",
            "compression_level": 10,
            "frame_duration": 60,
            "application": "audio"
        }    
    )
)

# Stream 2 is the subtitles stream from the first source (the 'mkv' file)
ff.output_maps.append(
    OutputMap(
        stream=2,
        specifier="Subtitles",
        options={
            "codec": "copy"
        }
    )
)

# Define the output file where everything will end up
ff.output_file = "/shared/output_file.mkv"

# Run the encode and make it verbose so we can see the progress.
ff.run(verbose=True)
```

### From a JSON file

The Python part is fairly straightforward:
```python
from ffmpeg import Ffmpeg

# Create the Ffmpeg object
ff = Ffmpeg()

# Load the JSON file with all of the settings
ff.load_from_file("test.json")

# Run the encode and make it verbose so we can see the progress.
ff.run(verbose=True)
```

The JSON file holds all of the information and gets processed to fill in all of the sources, source maps, output maps, and output file information.  It's also validated against the JSON schema file to ensure that the information is valid before it gets parsed.

This JSON example file has the exact same information in it as the "pure Python" example has in code.

```json
{
  "sources": [
    "source_file_1.mkv",
    "source_file_2.ac3"
  ],
  "source_maps": [
    {
      "source": 0,
      "specifier": "v",
      "stream": 0
    },
    {
      "source": 1,
      "specifier": "a",
      "stream": 0
    },
    {
      "source": 0,
      "specifier": "s",
      "stream": 0
    }
  ],
  "output_maps": [
    {
      "specifier": "v",
      "stream": 0,
      "options": {
        "codec": "libx265",
        "crf": 19,
        "pix_fmt": "yuv420p10le",
        "preset": "slow",
        "x265-params": {
          "limit-sao": 1,
          "bframes": 8,
          "psy-rd": 1,
          "psy-rdoq": 2,
          "aq-mode": 3
        }
      }
    },
    {
      "specifier": "a",
      "stream": 0,
      "options": {
        "codec": "libopus",
        "b": "128k",
        "ac": 2,
        "vbr": "on",
        "compression_level": 10,
        "frame_duration": 60,
        "application": "audio"
      }
    },
    {
      "specifier": "s",
      "stream": 0,
      "options": {
        "codec": "copy"
      }
    }
  ],
  "output_file": "/shared/output_file.mkv"
}
```