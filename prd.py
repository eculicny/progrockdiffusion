# -*- coding: utf-8 -*-
"""ProgRock Diffusion

Command line version of Disco Diffusion (v5 Alpha) adapted for command line by Jason Hough (and friends!)
--

Original file is located at
    https://colab.research.google.com/drive/1QGCyDlYneIvv1zFXngfOCCoSUKC6j1ZP

Original notebook by Katherine Crowson (https://github.com/crowsonkb, https://twitter.com/RiversHaveWings). It uses either OpenAI's 256x256 unconditional ImageNet or Katherine Crowson's fine-tuned 512x512 diffusion model (https://github.com/openai/guided-diffusion), together with CLIP (https://github.com/openai/CLIP) to connect text prompts with images.

Modified by Daniel Russell (https://github.com/russelldc, https://twitter.com/danielrussruss) to include (hopefully) optimal params for quick generations in 15-100 timesteps rather than 1000, as well as more robust augmentations.

Further improvements from Dango233 and nsheppard helped improve the quality of diffusion in general, and especially so for shorter runs like this notebook aims to achieve.

Vark added code to load in multiple Clip models at once, which all prompts are evaluated against, which may greatly improve accuracy.

The latest zoom, pan, rotation, and keyframes features were taken from Chigozie Nri's VQGAN Zoom Notebook (https://github.com/chigozienri, https://twitter.com/chigozienri)

Advanced DangoCutn Cutout method is also from Dango223.

Somnai (https://twitter.com/Somnai_dreams) added Diffusion Animation techniques, QoL improvements and various implementations of tech and techniques, mostly listed in the changelog below.

Pixel art models by u/Kaliyuga_ai

Comic faces model by alex_spirin

"""

# @title Licensed under the MIT License

# Copyright (c) 2021 Katherine Crowson

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

# @title <- View Changelog

import sys
import os

root_path = os.getcwd() # noqa: E402
sys.path.append(f'{root_path}/ResizeRight')  # noqa: E402
sys.path.append(f'{root_path}/CLIP')  # noqa: E402
sys.path.append(f'{root_path}/guided-diffusion')  # noqa: E402
sys.path.append(f'{root_path}/open_clip/src')  # noqa: E402

from cut_modules.make_cutouts import MakeCutoutsDango, MakeCutouts
from helpers.utils import fetch
from os.path import exists
import urllib.request
import hashlib
import random
import numpy as np
from datetime import datetime
import time
from guided_diffusion.script_util import create_model_and_diffusion, model_and_diffusion_defaults
from resize_right import resize
import clip
from tqdm import tqdm
import torchvision.transforms.functional as TF
from torch.nn import functional as F
from torch import nn
import torch
from typing import Text, List, Union
from types import SimpleNamespace
import json5 as json
from glob import glob
from PIL.PngImagePlugin import PngInfo
from PIL import Image, ImageOps, ImageStat, ImageEnhance, ImageDraw
import lpips
import timm
import math
import io
import gc
import re
import pandas as pd
import cv2
from functools import partial
from dataclasses import dataclass
import subprocess
from os import path
from pickle import FALSE
import shutil
import logging
import argparse
from helpers.vram_helpers import (
    track_model_vram,
    estimate_vram_requirements,
    log_max_allocated,
)
from model_managers.clip_manager import ClipManager, CLIP_NAME_MAP

from attr import has


# Simple create paths taken with modifications from Datamosh's Batch VQGAN+CLIP notebook
def createPath(filepath):
    if path.exists(filepath) == False:
        os.makedirs(filepath)
        print(f'Made {filepath}')
    else:
        pass


initDirPath = f'{root_path}/init_images'
createPath(initDirPath)
outDirPath = f'{root_path}/images_out'
createPath(outDirPath)

model_path = f'{root_path}/models'
createPath(model_path)

if os.getenv("LOCAL_CLIP_MODELS"):
    model_path_clip = model_path
else:
    home_dir = os.path.expanduser('~')
    model_path_clip = os.path.join(home_dir, ".cache", "clip")

model_256_downloaded = False
model_512_downloaded = False
model_secondary_downloaded = False

python_example = "python3"

if sys.platform == 'win32':
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    python_example = "python"

# Uncomment the below line if you're getting an error about OMP: Error #15.
# os.environ['KMP_DUPLICATE_LIB_OK']='TRUE'


# Setting default values for everything, which can then be overridden by settings files.
batch_name = "Default"
clip_guidance_scale = "auto"
tv_scale = 0
range_scale = 150
sat_scale = 0
n_batches = 1
display_rate = 20
cutn_batches = 4
cutn_batches_final = None
max_frames = 10000
interp_spline = "Linear"
init_image = None
init_masked = None
init_scale = 1000
skip_steps = 0
skip_steps_ratio = 0.0
frames_scale = 1500
frames_skip_steps = "60%"
perlin_init = False
perlin_mode = "mixed"
perlin_contrast = 1.0
perlin_brightness = 1.0
skip_augs = False
randomize_class = True
clip_denoised = False
clamp_grad = True
clamp_max = "auto"
set_seed = "random_seed"
fuzzy_prompt = False
rand_mag = 0.05
eta = "auto"
width_height = [832, 512]
width_height_scale = 1
diffusion_model = "512x512_diffusion_uncond_finetune_008100"
use_secondary_model = True
steps = 250
sampling_mode = "ddim"
diffusion_steps = 1000
ViTB32 = 1.0
ViTB16 = 0.0
ViTL14 = 0.0
ViTL14_336 = 0.0
RN101 = 0.0
RN50 = 0.0
RN50x4 = 0.0
RN50x16 = 0.0
RN50x64 = 0.0
ViTB32_laion2b_e16 = 1.0
ViTB32_laion400m_e31 = 0.0
ViTB32_laion400m_32 = 0.0
ViTB32quickgelu_laion400m_e31 = 0.0
ViTB32quickgelu_laion400m_e32 = 0.0
ViTB16_laion400m_e31 = 0.0
ViTB16_laion400m_e32 = 0.0
RN50_yffcc15m = 0.0
RN50_cc12m = 0.0
RN50_quickgelu_yfcc15m = 0.0
RN50_quickgelu_cc12m = 0.0
RN101_yfcc15m = 0.0
RN101_quickgelu_yfcc15m = 0.0
cut_overview = "[12]*400+[4]*600"
cut_innercut = "[4]*400+[12]*600"
cut_ic_pow = "[1]*500+[10]*500"
cut_ic_pow_final = None
cut_icgray_p = "[0.2]*400+[0]*600"
cut_heatmaps = False
smooth_schedules = False
key_frames = True
angle = "0:(0)"
zoom = "0: (1), 10: (1.05)"
translation_x = "0: (0)"
translation_y = "0: (0)"
video_init_path = "/content/training.mp4"
extract_nth_frame = 2
intermediate_saves = [0]
add_metadata = True
stop_early = 0
fix_brightness_contrast = True
adjustment_interval = 10
high_contrast_threshold = 80
high_contrast_adjust_amount = 0.85
high_contrast_start = 20
high_contrast_adjust = True
low_contrast_threshold = 20
low_contrast_adjust_amount = 2
low_contrast_start = 20
low_contrast_adjust = True
high_brightness_threshold = 180
high_brightness_adjust_amount = 0.85
high_brightness_start = 0
high_brightness_adjust = True
low_brightness_threshold = 40
low_brightness_adjust_amount = 1.15
low_brightness_start = 0
low_brightness_adjust = True
sharpen_preset = 'Off'  # @param ['Off', 'Faster', 'Fast', 'Slow', 'Very Slow']
keep_unsharp = False  # @param{type: 'boolean'}
animation_mode = "None"  # "Video Input", "2D"
gobig_scale = 2
gobig_skip_ratio = 0.6
gobig_overlap = 64
gobig_maximize = False
symmetry_loss_v = False
symmetry_loss_h = False
symm_loss_scale = "[2500]*1000"
symm_switch = 45
simple_symmetry = [0]
use_jpg = False
render_mask = None
cool_down = 0

# Command Line parse


def parse_args():
    example_text = f'''Usage examples:

    To simply use the 'Default' output directory and get settings from settings.json:
     {python_example} prd.py

    To use your own settings.json (note that putting it in quotes can help parse errors):
     {python_example} prd.py -s "some_directory/mysettings.json"

    Note that multiple settings files are allowed. They're parsed in order. The values present are applied over any previous value:
     {python_example} prd.py -s "some_directory/mysettings.json" -s "highres.json"

    To use the 'Default' output directory and settings, but override the output name and prompt:
     {python_example} prd.py -p "A cool image of the author of this program" -o Coolguy

    To use multiple prompts with optional weight values:
     {python_example} prd.py -p "A cool image of the author of this program" -p "Pale Blue Sky:.5"

    You can ignore the seed coming from a settings file by adding -i, resulting in a new random seed

    To force use of the CPU for image generation, add a -c or --cpu with how many threads to use (warning: VERY slow):
     {python_example} prd.py -c 16

    To generate a checkpoint image at 20% steps, for use as an init image in future runs, add -g or --geninit:
     {python_example} prd.py -g 

    To use a checkpoint image at 20% steps add -u or --useinit:
     {python_example} prd.py -u

    To specify which CUDA device to use (advanced) by device ID (default is 0):
     {python_example} prd.py --cuda 1

    To HIDE the settings that get added to your output PNG's metadata, use:
     {python_example} prd.py --hidemetadata

    To increase resolution 2x by splitting the final image and re-rendering detail in the sections, use:
     {python_example} prd.py --gobig

    To increase resolution 2x on an existing output, make sure to supply proper settings, and use:
     {python_example} prd.py --gobig --gobiginit "some_directory/image.png"

    Advanced gobiginit technique - supply a mask image as well (white = render, black = don't):
     {python_example} prd.py --gobig --gobiginit "some_directory/image.png" --gobigmask "some_directory/image.png"

    If you already upscaled your gobiginit image, you can skip the resizing process. Provide the scaling factor used:
     {python_example} prd.py --gobig --gobiginit "some_directory/image.png" --gobiginit_scaled 2

    To manually override the number of slices used for gobig:
     {python_example} prd.py --gobig --gobig_slices 6

    Alternative scaling method is to use ESRGAN (note: RealESRGAN must be installed and in your path):
     {python_example} prd.py --esrgan
    More information on instlaling it is here: https://github.com/xinntao/Real-ESRGAN
    '''

    my_parser = argparse.ArgumentParser(
        prog='ProgRockDiffusion',
        description='Generate images from text prompts.',
        epilog=example_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    my_parser.add_argument(
        '--gui',
        action='store_true',
        required=False,
        help='(deprecated, please invoke the gui separately)'
    )

    my_parser.add_argument(
        '-s',
        '--settings',
        action='append',
        required=False,
        default=['settings.json'],
        help='A settings JSON file to use, best to put in quotes. Multiples are allowed and layered in order.'
    )

    my_parser.add_argument(
        '-o',
        '--output',
        action='store',
        required=False,
        help='What output directory to use within images_out'
    )

    my_parser.add_argument(
        '-p',
        '--prompt',
        action='append',
        required=False,
        help='Override the prompt'
    )

    my_parser.add_argument(
        '-i',
        '--ignoreseed',
        action='store_true',
        required=False,
        help='Ignores the random seed in the settings file'
    )

    my_parser.add_argument(
        '-c',
        '--cpu',
        type=int,
        nargs='?',
        action='store',
        required=False,
        default=False,
        const=0,
        help='Force use of CPU instead of GPU, and how many threads to run'
    )

    my_parser.add_argument(
        '-g',
        '--geninit',
        type=int,
        nargs='?',
        action='store',
        required=False,
        default=False,
        const=20,
        help='Save a partial image at the specified percent of steps (1 to 99), for use as later init image'
    )
    my_parser.add_argument(
        '-u',
        '--useinit',
        action='store_true',
        required=False,
        default=False,
        help='Use the specified init image'
    )

    my_parser.add_argument(
        '--cuda',
        action='store',
        required=False,
        default='0',
        help='Which GPU to use. Default is 0.'
    )

    my_parser.add_argument(
        '--hidemetadata',
        action='store_true',
        required=False,
        help='Will prevent settings from being added to the output PNG file'
    )

    my_parser.add_argument(
        '--gobig',
        action='store_true',
        required=False,
        help='After generation, the image is split into sections and re-rendered, to double the size.'
    )

    my_parser.add_argument(
        '--gobiginit',
        action='store',
        required=False,
        help='An image to use to kick off GO BIG mode, skipping the initial render.'
    )

    my_parser.add_argument(
        '--gobigmask',
        action='store',
        required=False,
        help='An image mask for your gobig render, telling the system where to draw/not draw.'
    )

    my_parser.add_argument(
        '--gobiginit_scaled',
        type=int,
        nargs='?',
        action='store',
        required=False,
        default=False,
        const=2,
        help='If you already scaled your gobiginit image, add this option along with the multiplier used (default 2)'
    )

    my_parser.add_argument(
        '--gobig_slices',
        type=int,
        nargs='?',
        action='store',
        required=False,
        default=False,
        const=5,
        help='To manually override the calculated number of slices for gobig'
    )

    my_parser.add_argument(
        '--esrgan',
        action='store_true',
        required=False,
        help='Resize your output with ESRGAN (realesrgan-ncnn-vulkan must be in your path).'
    )

    my_parser.add_argument(
        '--skip_checks',
        action='store_true',
        required=False,
        default=False,
        help='Do not check values to make sure they are sensible.'
    )

    my_parser.add_argument(
        '--log_level',
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Specify the log level. (default: 'INFO')"
    )

    my_parser.add_argument(
        '--cut_debug',
        action="store_true",
        help="Output cut debug images."
    )

    return my_parser.parse_args()


cl_args = parse_args()


# Configure logging
numeric_log_level = numeric_level = getattr(logging, cl_args.log_level, None)
if not isinstance(numeric_level, int):
    raise ValueError(f"Invalid log level: {cl_args.log_level}")
logging.basicConfig(level=numeric_level)
logger = logging.getLogger(__name__)


# Simple check to see if a key is present in the settings file
def is_json_key_present(json, key, subkey="none"):
    try:
        if subkey != "none":
            buf = json[key][subkey]
        else:
            buf = json[key]
    except KeyError:
        return False
    if type(buf) == type(None):
        return False
    return True


# A simple way to ensure values are in an accceptable range, and also return a random value if desired
def clampval(var_name, minval, val, maxval):
    if val == "random":
        try:
            val = random.randint(minval, maxval)
        except:
            val = random.uniform(minval, maxval)
        return val
    # Auto is handled later, so we just return it back as is
    elif val == "auto":
        return val
    elif type(val) == str:
        return val
    elif val < minval and not cl_args.skip_checks:
        print(f'Warning: {var_name} is below {minval} - if you get bad results, consider adjusting.')
        return val
    elif val > maxval and not cl_args.skip_checks:
        print(f'Warning: {var_name} is above {maxval} - if you get bad results, consider adjusting.')
        return val
    else:
        return val

# Dynamic value - takes ready-made possible options within a string and returns the string with an option randomly selected
# Format is "I will return <Value1|Value2|Value3> in this string"
# Which would come back as "I will return Value2 in this string" (for example)
# Optionally if a value of ^^# is first, it means to return that many dynamic values,
# so <^^2|Value1|Value2|Value3> in the above example would become:
# "I will return Value3 Value2 in this string"
# note: for now assumes a string for return. TODO return a desired type


def dynamic_value(incoming):
    if type(incoming) == str:  # we only need to do something if it's a string...
        if incoming == "auto" or incoming == "random":
            return incoming
        elif "<" in incoming:   # ...and if < is in the string...
            text = incoming
            logger.debug(f'Original value: {text}')
            while "<" in text:
                start = text.index('<')
                end = text.index('>')
                swap = text[(start + 1):end]
                value = ""
                count = 1
                values = swap.split('|')
                if "^^" in values[0]:
                    count = values[0]
                    values.pop(0)
                    count = int(count[2:])
                random.shuffle(values)
                for i in range(count):
                    value = value + values[i] + " "
                value = value[:-1]  # remove final space
                text = text.replace(f'<{swap}>', value)
            logger.debug(f'Dynamic value: {text}')
            return text
        else:
            return incoming
    else:
        return incoming


print('\nPROG ROCK DIFFUSION')
print('-------------------')

# rolling a d20 to see if I should pester you about supporting PRD.
# Apologies if this offends you. At least it's only on a critical miss, right?
d20 = random.randint(1, 20)
if d20 == 1:
    print('Please consider supporting my Patreon. Thanks! https://is.gd/rVX6IH')
else:
    print('')

# Load the JSON config files
for setting_arg in cl_args.settings:
    try:
        with open(setting_arg, 'r', encoding="utf-8") as json_file:
            print(f'Parsing {setting_arg}')
            settings_file = json.load(json_file)
            # If any of these are in this settings file they'll be applied, overwriting any previous value.
            # Some are passed through clampval first to make sure they are within bounds (or randomized if desired)
            if is_json_key_present(settings_file, 'batch_name'):
                batch_name = (settings_file['batch_name'])
            if is_json_key_present(settings_file, 'text_prompts'):
                text_prompts = (settings_file['text_prompts'])
            if is_json_key_present(settings_file, 'image_prompts'):
                image_prompts = (settings_file['image_prompts'])
            if is_json_key_present(settings_file, 'clip_guidance_scale'):
                if (type(settings_file['clip_guidance_scale']) == str) and ((settings_file['clip_guidance_scale']) != "random"):
                    clip_guidance_scale = dynamic_value(settings_file['clip_guidance_scale'])
                else:
                    clip_guidance_scale = clampval('clip_guidance_scale', 1500, (settings_file['clip_guidance_scale']), 100000)
            if is_json_key_present(settings_file, 'tv_scale'):
                if (settings_file['tv_scale']) != "auto" and (settings_file['tv_scale']) != "random":
                    tv_scale = int(dynamic_value(settings_file['tv_scale']))
                tv_scale = clampval('tv_scale', 0, tv_scale, 1000)
            if is_json_key_present(settings_file, 'range_scale'):
                if (settings_file['range_scale']) != "auto" and (settings_file['range_scale']) != "random":
                    range_scale = int(dynamic_value(settings_file['range_scale']))
                range_scale = clampval('range_scale', 0, range_scale, 1000)
            if is_json_key_present(settings_file, 'sat_scale'):
                if (settings_file['sat_scale']) != "auto" and (settings_file['sat_scale']) != "random":
                    sat_scale = int(dynamic_value(settings_file['sat_scale']))
                sat_scale = clampval('sat_scale', 0, sat_scale, 20000)
            if is_json_key_present(settings_file, 'n_batches'):
                n_batches = (settings_file['n_batches'])
            if is_json_key_present(settings_file, 'display_rate'):
                display_rate = (settings_file['display_rate'])
            if is_json_key_present(settings_file, 'cutn_batches'):
                if type(settings_file['cutn_batches']) == str:
                    cutn_batches = dynamic_value(settings_file['cutn_batches'])
                else:
                    cutn_batches = (settings_file['cutn_batches'])
            if is_json_key_present(settings_file, 'cutn_batches_final'):
                cutn_batches_final = (settings_file['cutn_batches_final'])
            if is_json_key_present(settings_file, 'max_frames'):
                max_frames = (settings_file['max_frames'])
            if is_json_key_present(settings_file, 'interp_spline'):
                interp_spline = (settings_file['interp_spline'])
            if is_json_key_present(settings_file, 'init_image'):
                init_image = (settings_file['init_image'])
            if is_json_key_present(settings_file, 'init_masked'):
                init_masked = (settings_file['init_masked'])
            if is_json_key_present(settings_file, 'init_scale'):
                init_scale = (settings_file['init_scale'])
            if is_json_key_present(settings_file, 'skip_steps'):
                skip_steps = int(dynamic_value(settings_file['skip_steps']))
            if is_json_key_present(settings_file, 'skip_steps_ratio'):
                skip_steps_ratio = (settings_file['skip_steps_ratio'])
            if is_json_key_present(settings_file, 'stop_early'):
                stop_early = (settings_file['stop_early'])
            if is_json_key_present(settings_file, 'frames_scale'):
                frames_scale = (settings_file['frames_scale'])
            if is_json_key_present(settings_file, 'frames_skip_steps'):
                frames_skip_steps = (settings_file['frames_skip_steps'])
            if is_json_key_present(settings_file, 'perlin_init'):
                perlin_init = (settings_file['perlin_init'])
            if is_json_key_present(settings_file, 'perlin_mode'):
                perlin_mode = (settings_file['perlin_mode'])
            if is_json_key_present(settings_file, 'perlin_contrast'):
                perlin_contrast = (settings_file['perlin_contrast'])
            if is_json_key_present(settings_file, 'perlin_brightness'):
                perlin_brightness = (settings_file['perlin_brightness'])
            if is_json_key_present(settings_file, 'skip_augs'):
                skip_augs = (settings_file['skip_augs'])
            if is_json_key_present(settings_file, 'randomize_class'):
                randomize_class = (settings_file['randomize_class'])
            if is_json_key_present(settings_file, 'clip_denoised'):
                clip_denoised = (settings_file['clip_denoised'])
            if is_json_key_present(settings_file, 'clamp_grad'):
                clamp_grad = (settings_file['clamp_grad'])
            if is_json_key_present(settings_file, 'clamp_max'):
                if (type(settings_file['clamp_max']) == str) and ((settings_file['clamp_max']) != "random"):
                    clamp_max = dynamic_value(settings_file['clamp_max'])
                else:
                    clamp_max = clampval('clamp_max', 0.001, settings_file['clamp_max'], 0.3)
            if is_json_key_present(settings_file, 'set_seed'):
                set_seed = (settings_file['set_seed'])
            if is_json_key_present(settings_file, 'fuzzy_prompt'):
                fuzzy_prompt = (settings_file['fuzzy_prompt'])
            if is_json_key_present(settings_file, 'rand_mag'):
                rand_mag = clampval('rand_mag', 0.0, (settings_file['rand_mag']), 0.999)
            if is_json_key_present(settings_file, 'eta'):
                if (settings_file['eta']) != "auto" and (settings_file['eta']) != "random":
                    eta = float(dynamic_value(settings_file['eta']))
                eta = clampval('eta', 0.0, eta, 0.999)
            if is_json_key_present(settings_file, 'width'):
                width_height = [(settings_file['width']),
                                (settings_file['height'])]
            if is_json_key_present(settings_file, 'width_height_scale'):
                width_height_scale = (settings_file['width_height_scale'])
            if is_json_key_present(settings_file, 'diffusion_model'):
                diffusion_model = (settings_file['diffusion_model'])
            if is_json_key_present(settings_file, 'use_secondary_model'):
                use_secondary_model = (settings_file['use_secondary_model'])
            if is_json_key_present(settings_file, 'steps'):
                steps = int(dynamic_value(settings_file['steps']))
            if is_json_key_present(settings_file, 'sampling_mode'):
                sampling_mode = (settings_file['sampling_mode'])
            if is_json_key_present(settings_file, 'diffusion_steps'):
                diffusion_steps = (settings_file['diffusion_steps'])
            if is_json_key_present(settings_file, 'ViTB32'):
                ViTB32 = float(dynamic_value(settings_file['ViTB32']))
            if is_json_key_present(settings_file, 'ViTB16'):
                ViTB16 = float(dynamic_value(settings_file['ViTB16']))
            if is_json_key_present(settings_file, 'ViTL14'):
                ViTL14 = float(dynamic_value(settings_file['ViTL14']))
            if is_json_key_present(settings_file, 'ViTL14_336'):
                ViTL14_336 = float(dynamic_value(settings_file['ViTL14_336']))
            if is_json_key_present(settings_file, 'RN101'):
                RN101 = float(dynamic_value(settings_file['RN101']))
            if is_json_key_present(settings_file, 'RN50'):
                RN50 = float(dynamic_value(settings_file['RN50']))
            if is_json_key_present(settings_file, 'RN50x4'):
                RN50x4 = float(dynamic_value(settings_file['RN50x4']))
            if is_json_key_present(settings_file, 'RN50x16'):
                RN50x16 = float(dynamic_value(settings_file['RN50x16']))
            if is_json_key_present(settings_file, 'RN50x64'):
                RN50x64 = float(dynamic_value(settings_file['RN50x64']))
            if is_json_key_present(settings_file, 'ViTB32_laion2b_e16'):
                ViTB32_laion2b_e16 = float(dynamic_value(settings_file['ViTB32_laion2b_e16']))
            if is_json_key_present(settings_file, 'ViTB32_laion400m_e31'):
                ViTB32_laion400m_e31 = float(dynamic_value(settings_file['ViTB32_laion400m_e31']))
            if is_json_key_present(settings_file, 'ViTB32_laion400m_32'):
                ViTB32_laion400m_32 = float(dynamic_value(settings_file['ViTB32_laion400m_32']))
            if is_json_key_present(settings_file, 'ViTB32quickgelu_laion400m_e31'):
                ViTB32quickgelu_laion400m_e31 = float(dynamic_value(settings_file['ViTB32quickgelu_laion400m_e31']))
            if is_json_key_present(settings_file, 'ViTB32quickgelu_laion400m_e32'):
                ViTB32quickgelu_laion400m_e32 = float(dynamic_value(settings_file['ViTB32quickgelu_laion400m_e32']))
            if is_json_key_present(settings_file, 'ViTB16_laion400m_e31'):
                ViTB16_laion400m_e31 = float(dynamic_value(settings_file['ViTB16_laion400m_e31']))
            if is_json_key_present(settings_file, 'ViTB16_laion400m_e32'):
                ViTB16_laion400m_e32 = float(dynamic_value(settings_file['ViTB16_laion400m_e32']))
            if is_json_key_present(settings_file, 'RN50_yffcc15m'):
                RN50_yffcc15m = float(dynamic_value(settings_file['RN50_yffcc15m']))
            if is_json_key_present(settings_file, 'RN50_cc12m'):
                RN50_cc12m = float(dynamic_value(settings_file['RN50_cc12m']))
            if is_json_key_present(settings_file, 'RN50_quickgelu_yfcc15m'):
                RN50_quickgelu_yfcc15m = float(dynamic_value(settings_file['RN50_quickgelu_yfcc15m']))
            if is_json_key_present(settings_file, 'RN50_quickgelu_cc12m'):
                RN50_quickgelu_cc12m = float(dynamic_value(settings_file['RN50_quickgelu_cc12m']))
            if is_json_key_present(settings_file, 'RN101_yfcc15m'):
                RN101_yfcc15m = float(dynamic_value(settings_file['RN101_yfcc15m']))
            if is_json_key_present(settings_file, 'RN101_quickgelu_yfcc15m'):
                RN101_quickgelu_yfcc15m = float(dynamic_value(settings_file['RN101_quickgelu_yfcc15m']))
            if is_json_key_present(settings_file, 'cut_overview'):
                cut_overview = dynamic_value(settings_file['cut_overview'])
            if is_json_key_present(settings_file, 'cut_innercut'):
                cut_innercut = dynamic_value(settings_file['cut_innercut'])
            if is_json_key_present(settings_file, 'cut_ic_pow'):
                if (type(settings_file['cut_ic_pow']) == str) and ((settings_file['cut_ic_pow']) != "random"):
                    cut_ic_pow = dynamic_value(settings_file['cut_ic_pow'])
                else:
                    cut_ic_pow = clampval('cut_ic_pow', 0.0, (settings_file['cut_ic_pow']), 100)
            if is_json_key_present(settings_file, 'cut_ic_pow_final'):
                cut_ic_pow_final = clampval('cut_ic_pow_final', 0.5, (settings_file['cut_ic_pow_final']), 100)
            if is_json_key_present(settings_file, 'cut_icgray_p'):
                cut_icgray_p = (settings_file['cut_icgray_p'])
            if is_json_key_present(settings_file, 'cut_heatmaps'):
                cut_heatmaps = (settings_file['cut_heatmaps'])
            if is_json_key_present(settings_file, 'smooth_schedules'):
                smooth_schedules = (settings_file['smooth_schedules'])
            if is_json_key_present(settings_file, 'key_frames'):
                key_frames = (settings_file['key_frames'])
            if is_json_key_present(settings_file, 'angle'):
                angle = (settings_file['angle'])
            if is_json_key_present(settings_file, 'zoom'):
                zoom = (settings_file['zoom'])
            if is_json_key_present(settings_file, 'translation_x'):
                translation_x = (settings_file['translation_x'])
            if is_json_key_present(settings_file, 'translation_y'):
                translation_y = (settings_file['translation_y'])
            if is_json_key_present(settings_file, 'video_init_path'):
                video_init_path = (settings_file['video_init_path'])
            if is_json_key_present(settings_file, 'extract_nth_frame'):
                extract_nth_frame = (settings_file['extract_nth_frame'])
            if is_json_key_present(settings_file, 'intermediate_saves'):
                intermediate_saves = (settings_file['intermediate_saves'])
            if is_json_key_present(settings_file, 'fix_brightness_contrast'):
                fix_brightness_contrast = (settings_file['fix_brightness_contrast'])
            if is_json_key_present(settings_file, 'adjustment_interval'):
                adjustment_interval = (settings_file['adjustment_interval'])
            if is_json_key_present(settings_file, 'high_contrast_threshold'):
                high_contrast_threshold = (settings_file['high_contrast_threshold'])
            if is_json_key_present(settings_file, 'high_contrast_adjust_amount'):
                high_contrast_adjust_amount = (settings_file['high_contrast_adjust_amount'])
            if is_json_key_present(settings_file, 'high_contrast_start'):
                high_contrast_start = (settings_file['high_contrast_start'])
            if is_json_key_present(settings_file, 'high_contrast_adjust'):
                high_contrast_adjust = (settings_file['high_contrast_adjust'])
            if is_json_key_present(settings_file, 'low_contrast_threshold'):
                low_contrast_threshold = (settings_file['low_contrast_threshold'])
            if is_json_key_present(settings_file, 'low_contrast_adjust_amount'):
                low_contrast_adjust_amount = (settings_file['low_contrast_adjust_amount'])
            if is_json_key_present(settings_file, 'low_contrast_start'):
                low_contrast_start = (settings_file['low_contrast_start'])
            if is_json_key_present(settings_file, 'low_contrast_adjust'):
                low_contrast_adjust = (settings_file['low_contrast_adjust'])
            if is_json_key_present(settings_file, 'high_brightness_threshold'):
                high_brightness_threshold = (settings_file['high_brightness_threshold'])
            if is_json_key_present(settings_file, 'high_brightness_adjust_amount'):
                high_brightness_adjust_amount = (settings_file['high_brightness_adjust_amount'])
            if is_json_key_present(settings_file, 'high_brightness_start'):
                high_brightness_start = (settings_file['high_brightness_start'])
            if is_json_key_present(settings_file, 'high_brightness_adjust'):
                high_brightness_adjust = (settings_file['high_brightness_adjust'])
            if is_json_key_present(settings_file, 'low_brightness_threshold'):
                low_brightness_threshold = (settings_file['low_brightness_threshold'])
            if is_json_key_present(settings_file, 'low_brightness_adjust_amount'):
                low_brightness_adjust_amount = (settings_file['low_brightness_adjust_amount'])
            if is_json_key_present(settings_file, 'low_brightness_start'):
                low_brightness_start = (settings_file['low_brightness_start'])
            if is_json_key_present(settings_file, 'low_brightness_adjust'):
                low_brightness_adjust = (settings_file['low_brightness_adjust'])
            if is_json_key_present(settings_file, 'sharpen_preset'):
                sharpen_preset = (settings_file['sharpen_preset'])
            if is_json_key_present(settings_file, 'keep_unsharp'):
                keep_unsharp = (settings_file['keep_unsharp'])
            if is_json_key_present(settings_file, 'animation_mode'):
                animation_mode = (settings_file['animation_mode'])
            if is_json_key_present(settings_file, 'gobig_scale'):
                gobig_scale = int(settings_file['gobig_scale'])
            if is_json_key_present(settings_file, 'gobig_skip_ratio'):
                gobig_skip_ratio = (settings_file['gobig_skip_ratio'])
            if is_json_key_present(settings_file, 'gobig_overlap'):
                gobig_overlap = (settings_file['gobig_overlap'])
            if is_json_key_present(settings_file, 'gobig_maximize'):
                gobig_maximize = (settings_file['gobig_maximize'])
            if is_json_key_present(settings_file, 'symmetry_loss'):
                symmetry_loss_v = (settings_file['symmetry_loss'])
                print("symmetry_loss was depracated, please use symmetry_loss_v in the future")
            if is_json_key_present(settings_file, 'symmetry_loss_v'):
                symmetry_loss_v = (settings_file['symmetry_loss_v'])
            if is_json_key_present(settings_file, 'symmetry_loss_h'):
                symmetry_loss_h = (settings_file['symmetry_loss_h'])
            if is_json_key_present(settings_file, 'sloss_scale'):
                print('"sloss_scale" is deprecated. Please update your settings to use "symm_loss_scale"')
                symm_loss_scale = (settings_file['sloss_scale'])
            if is_json_key_present(settings_file, 'symm_loss_scale'):
                if type(settings_file['symm_loss_scale']) == str:
                    symm_loss_scale = dynamic_value(settings_file['symm_loss_scale'])
                else:
                    symm_loss_scale = (settings_file['symm_loss_scale'])
            if is_json_key_present(settings_file, 'symm_switch'):
                symm_switch = int(clampval('symm_switch', 1, (settings_file['symm_switch']), steps))
            if is_json_key_present(settings_file, 'simple_symmetry'):
                simple_symmetry = (settings_file['simple_symmetry'])
            if is_json_key_present(settings_file, 'use_jpg'):
                use_jpg = (settings_file['use_jpg'])
            if is_json_key_present(settings_file, 'render_mask'):
                render_mask = (settings_file['render_mask'])
            if is_json_key_present(settings_file, 'cool_down'):
                cool_down = (settings_file['cool_down'])

    except Exception as e:
        print('Failed to open or parse ' + setting_arg + ' - Check formatting.')
        print(e)
        quit()

print('')

width_height = [width_height[0] * width_height_scale, width_height[1] * width_height_scale]

if symmetry_loss_v or symmetry_loss_h:
    print(f"Symmetry will end at step {symm_switch}")

# Now override some depending on command line and maybe a special case
if cl_args.output:
    batch_name = cl_args.output
    print(f'Setting Output dir to {batch_name}')

if cl_args.ignoreseed:
    set_seed = 'random_seed'
    print(f'Using a random seed instead of the one provided by the JSON file.')

try:
    environ_hidemetadata = os.environ.get('PRD_HIDE_METADATA')
except:
    environ_hidemetadata = False

if cl_args.hidemetadata or environ_hidemetadata:
    add_metadata = False
    print(f'Hide metadata flag is ON, settings will not be stored in the PNG output.')

letsgobig = False
gobig_vertical = False
if cl_args.gobig:
    letsgobig = True
    gobig_vertical = True
    if cl_args.gobiginit:
        init_image = cl_args.gobiginit
        print(f'Using {init_image} to kickstart GO BIG. Initial render will be skipped.')
        # check to make sure it is a multiple of 64, otherwise resize it and let the user know.
        temp_image = Image.open(init_image)
        s_width, s_height = temp_image.size
        reside_x = (s_width // 64) * 64
        reside_y = (s_height // 64) * 64
        if reside_x != s_width or reside_y != s_height:
            print('ERROR: Your go big init resolution was NOT a multiple of 64.')
            print('ERROR: Please resize your image.')
            raise Exception("Exiting due to improperly sized go big init.")
        side_x, side_y = temp_image.size
        width_height[0] = side_x
        width_height[1] = side_y
        temp_image.close
        if cl_args.gobigmask:
            render_mask = cl_args.gobigmask # might need to do the same checks here as above for init, but for now let's give the user a little credit.
    else:
        cl_args.gobiginit = None
    if cl_args.gobiginit_scaled != False:
        gobig_scale = cl_args.gobiginit_scaled

if cl_args.geninit:
    geninit = True
    if cl_args.geninit > 0 and cl_args.geninit <= 100:
        geninitamount = float(cl_args.geninit / 100)  # turn it into a float percent
        print(f'GenInit mode enabled. A checkpoint image will be saved at {cl_args.geninit:.1%} of steps.')
    else:
        geninitamount = 0.2
        print(f'GenInit mode enabled. Provided number was out of bounds, so using {geninitamount:.1%} of steps instead.')
else:
    geninit = False

if skip_steps == 0 and ((init_image is not None) or (perlin_init == True)):
    if 0 < skip_steps_ratio <= 1:
        skip_steps = (int(steps * skip_steps_ratio))
    else:
        skip_steps = (int(steps * 0.33))

if cl_args.useinit:
    if skip_steps == 0:
        skip_steps = (int(steps * 0.2))  # don't change skip_steps if the settings file specified one
    if path.exists(f'{cl_args.useinit}'):
        useinit = True
        init_image = cl_args.useinit
        print(f'UseInit mode is using {cl_args.useinit} and starting at {skip_steps}.')
    else:
        init_image = 'geninit.png'
        if path.exists(init_image):
            print(f'UseInit mode is using {init_image} and starting at {skip_steps}.')
            useinit = True
        else:
            print('No init image found. Uneinit mode canceled.')
            useinit = False
else:
    useinit = False


def val_interpolate(x1, y1, x2, y2, x):
    # Linear interpolation. Return y between y1 and y2 for the same position x is bettewen x1 and x2
    d = [[x1, y1], [x2, y2]]
    output = d[0][1] + (x - d[0][0]) * ((d[1][1] - d[0][1])/(d[1][0] - d[0][0]))
    if type(y1) == int:
        output = int(output)  # return the proper type
    return(output)


def num_to_schedule(input, final=-9999):
    # take a single number and turn it into a string-style schedule, with support for interpolated
    if final != -9999:
        output = (f"[{input}]*1+")
        for i in range(1, 1000):
            percent_done = i / 1000
            val = val_interpolate(1, input, 1000, final, i)
            output = output + (f"[{val}]*1+")
        output = output[:-1]  # remove the final plus character
    else:
        output = (f'[{input}]*1000')
    return(output)


# Automatic Eta based on steps
if eta == 'auto':
    maxetasteps = 315
    minetasteps = 50
    maxeta = 1.0
    mineta = 0.0
    if steps > maxetasteps:
        eta = maxeta
    elif steps < minetasteps:
        eta = mineta
    else:
        stepsrange = (maxetasteps - minetasteps)
        newrange = (maxeta - mineta)
        eta = (((steps - minetasteps) * newrange) / stepsrange) + mineta
        eta = round(eta, 2)
        print(f'Eta set automatically to: {eta}')

# Automatic clamp_max based on steps
if clamp_max == 'auto':
    if steps <= 35:
        clamp_max = 0.001
    elif steps <= 75:
        clamp_max = 0.0125
    elif steps <= 150:
        clamp_max = 0.02
    elif steps <= 225:
        clamp_max = 0.035
    elif steps <= 300:
        clamp_max = 0.05
    elif steps <= 500:
        clamp_max = 0.075
    else:
        clamp_max = 0.1
    if use_secondary_model == False:
        clamp_max = clamp_max * 2
    clamp_max = num_to_schedule(clamp_max)
    print(f'Clamp_max automatically set to {clamp_max}')
elif type(clamp_max) != str:
    clamp_max = num_to_schedule(clamp_max)
    print(f'Converted clamp_max to schedule, new value is: {clamp_max}')

# Automatic clip_guidance_scale based on overall resolution
if clip_guidance_scale == 'auto':
    res = width_height[0] * width_height[1]  # total pixels
    maxcgsres = 2000000
    mincgsres = 250000
    maxcgs = 50000
    mincgs = 2500
    if res > maxcgsres:
        clip_guidance_scale = maxcgs
    elif res < mincgsres:
        clip_guidance_scale = mincgs
    else:
        resrange = (maxcgsres - mincgsres)
        newrange = (maxcgs - mincgs)
        clip_guidance_scale = (((res - mincgsres) * newrange) / resrange) + mincgs
        clip_guidance_scale = round(clip_guidance_scale)
    clip_guidance_scale = num_to_schedule(clip_guidance_scale)
    print(f'clip_guidance_scale set automatically to: {clip_guidance_scale}')

if type(symm_loss_scale) != str:
    symm_loss_scale = num_to_schedule(symm_loss_scale)

og_cutn_batches = cutn_batches
if type(cutn_batches) != str:
    if cutn_batches_final != None:
        cutn_batches = num_to_schedule(cutn_batches, cutn_batches_final)
    else:
        cutn_batches = num_to_schedule(cutn_batches)
    print(f'Converted cutn_batches to schedule.')
    logger.debug(f'cutn_batches schedule is: {cutn_batches}')

if cl_args.prompt:
    text_prompts["0"] = cl_args.prompt
    print(f'Setting prompt to {text_prompts}')

# PROMPT RANDOMIZERS
# If any word in the prompt starts and ends with _, replace it with a random line from the corresponding text file
# For example, _artist_ will replace with a line from artist.txt

# Build a list of randomizers to draw from:


def randomizer(category):
    random.seed()
    randomizers = []
    with open(f'settings/{category}.txt', encoding="utf-8") as f:
        for line in f:
            randomizers.append(line.strip())
    random_item = random.choice(randomizers)
    return(random_item)


def randomize_prompts(prompts):
    # take a list of prompts and handle any _random_ elements
    newprompts = []
    for prompt in prompts:
        if "<" in prompt:
            newprompt = dynamic_value(prompt)
        else:
            newprompt = prompt
        if "_" in newprompt:
            while "_" in newprompt:
                start = newprompt.index('_')
                end = newprompt.index('_', start+1)
                swap = newprompt[(start + 1):end]
                swapped = randomizer(swap)
                newprompt = newprompt.replace(f'_{swap}_', swapped, 1)
        newprompts.append(newprompt)
    return newprompts


# Ugly, but we need to convert the prompts that we get so that their key values are numbers instead of strings
# plus we need to handle any randomizers, so we do that all here, too.
converted_prompts = {}
for k, v in text_prompts.items():
    k = int(k)  # convert the key value to an integer
    if type(v) != list:
        converted_inner_prompts = {}
        # handle dict verison here
        for i_k, i_v in v.items():
            i_k = int(i_k)
            i_v = randomize_prompts(i_v)
            converted_inner_prompts.update({i_k: i_v})
        v = converted_inner_prompts
        converted_prompts.update({k: v})
    else:
        v = randomize_prompts(v)
        converted_prompts.update({k: v})
text_prompts = converted_prompts

print('\nPrompt(s) with randomizers:')
for k, v in text_prompts.items():
    print(f'  {k}: {v}')
print('\n')


# INIT IMAGE RANDOMIZER
# If the setting for init_image is a word between two underscores, we'll pull a random image from that directory,
# and set our size accordingly.

# randomly pick a file name from a directory:
def random_file(directory):
    files = []
    files = os.listdir(f'{initDirPath}/{directory}')
    file = random.choice(files)
    return(file)


def get_resampling_mode():
    try:
        from PIL import __version__, Image
        major_ver = int(__version__.split('.')[0])
        if major_ver >= 9:
            return Image.Resampling.LANCZOS
        else:
            return Image.LANCZOS
    except Exception as ex:
        return 1  # 'Lanczos' irrespective of version.


# Check for init randomizer in settings, and configure a random init if found
init_image_OriginalPath = init_image
if init_image != None:
    if init_image.startswith("_") and init_image.endswith("_"):
        randominit_dir = (init_image[1:])
        randominit_dir = (randominit_dir[:-1])  # parse out the directory name
        print(f"Randomly picking an init image from {initDirPath}/{randominit_dir}")
        init_image_OriginalPath = init_image = (f'{initDirPath}/{randominit_dir}/{random_file(randominit_dir)}')
        print(f"New init image is {init_image}")
        # check to see if the image matches the configured size, if not we'll resize it
        temp = Image.open(init_image).convert('RGB')
        temp_width, temp_height = temp.size
        if (temp_width != width_height[0]) or (temp_height != width_height[1]):
            print('Randomly chosen init image does not match width and height from settings.')
            print('It will be resized as temp_init.png and used as your init.')
            temp = temp.resize(width_height, get_resampling_mode())
            temp.save('temp_init.png')
            init_image = 'temp_init.png'

# Decide if we're using CPU or GPU, with appropriate settings depending...
if cl_args.cpu or not torch.cuda.is_available():
    DEVICE = torch.device('cpu')
    device = DEVICE
    fp16_mode = False
    cores = os.cpu_count()
    if cl_args.cpu == 0:
        print(f'No thread count specified. Using detected {cores} cores for CPU mode.')
    elif cl_args.cpu > cores:
        print(f'Too many threads specified. Using detected {cores} cores for CPU mode.')
    else:
        cores = int(cl_args.cpu)
        print(f'Using {cores} cores for CPU mode.')
    torch.set_num_threads(cores)
else:
    DEVICE = torch.device(f'cuda:{cl_args.cuda}')
    device = DEVICE
    fp16_mode = True
    if torch.cuda.get_device_capability(device) == (8, 0):  # A100 fix thanks to Emad
        print('Disabling CUDNN for A100 gpu', file=sys.stderr)
        torch.backends.cudnn.enabled = False

print('Pytorch is using device:', device)

# @title 2.2 Define necessary functions


def ease(num, t):
    start = num[0]
    end = num[1]
    power = num[2]
    return start + pow(t, power) * (end - start)


def interp(t):
    return 3 * t**2 - 2 * t**3


def smooth_jazz(schedule):
    # Take a list of numbers (i.e. an already-evaluated schedule),
    # find the places where the number changes from one to the next, and smooth those transitions
    newschedule = schedule
    zone = int(len(schedule) * .05)  # We want to smooth a transition for 50 steps in a 1000 step scenario
    markers = []
    last_num = schedule[0]
    # build a list of indicies of where the number changes
    for i in range(1, len(schedule)):
        current_num = schedule[i]
        if current_num != last_num:
            markers.append(i)
        last_num = current_num
    # now smooth out the surrounding numbers for any markers we have
    lastindex = 0
    if len(markers) > 0:
        for index in markers:
            if (index - lastindex) >= (zone / 2):  # only smooth if the indexes are far enough apart
                start = int(index - (zone / 2))
                if start < 1:
                    start = 1  # make sure we stay within the range of the array
                end = int(index + (zone / 2))
                if end > len(schedule):
                    end = len(schedule)  # make sure we stay within the range of the array
                i = start
                while i < end:
                    newschedule[i] = val_interpolate(start, schedule[start], end, schedule[end], i)
                    i += 1
            lastindex = index
    return(newschedule)


def perlin(width, height, scale=10, device=None):
    gx, gy = torch.randn(2, width + 1, height + 1, 1, 1, device=device)
    xs = torch.linspace(0, 1, scale + 1)[:-1, None].to(device)
    ys = torch.linspace(0, 1, scale + 1)[None, :-1].to(device)
    wx = 1 - interp(xs)
    wy = 1 - interp(ys)
    dots = 0
    dots += wx * wy * (gx[:-1, :-1] * xs + gy[:-1, :-1] * ys)
    dots += (1 - wx) * wy * (-gx[1:, :-1] * (1 - xs) + gy[1:, :-1] * ys)
    dots += wx * (1 - wy) * (gx[:-1, 1:] * xs - gy[:-1, 1:] * (1 - ys))
    dots += (1 - wx) * (1 - wy) * (-gx[1:, 1:] * (1 - xs) - gy[1:, 1:] * (1 - ys))
    return dots.permute(0, 2, 1, 3).contiguous().view(width * scale, height * scale)


def perlin_ms(octaves, width, height, grayscale, device=device):
    out_array = [0.5] if grayscale else [0.5, 0.5, 0.5]
    # out_array = [0.0] if grayscale else [0.0, 0.0, 0.0]
    for i in range(1 if grayscale else 3):
        scale = 2**len(octaves)
        oct_width = width
        oct_height = height
        for oct in octaves:
            p = perlin(oct_width, oct_height, scale, device)
            out_array[i] += p * oct
            scale //= 2
            oct_width *= 2
            oct_height *= 2
    return torch.cat(out_array)


def create_perlin_noise(octaves=[1, 1, 1, 1], width=2, height=2, grayscale=True):
    out = perlin_ms(octaves, width, height, grayscale)
    if grayscale:
        out = TF.resize(size=(side_y, side_x), img=out.unsqueeze(0))
        out = TF.to_pil_image(out.clamp(0, 1)).convert('RGB')
    else:
        out = out.reshape(-1, 3, out.shape[0] // 3, out.shape[1])
        out = TF.resize(size=(side_y, side_x), img=out)
        out = TF.to_pil_image(out.clamp(0, 1).squeeze())

    # out = ImageOps.autocontrast(out, preserve_tone=True)
    out = ImageOps.autocontrast(out)
    if perlin_contrast != 1.0:
        out2 = ImageEnhance.Contrast(out)
        out3 = out2.enhance(perlin_contrast)
        out = out3
    if perlin_brightness != 1.0:
        out2 = ImageEnhance.Brightness(out)
        out3 = out2.enhance(perlin_brightness)
        out = out3
    return out


def gen_perlin():
    if perlin_mode == 'color':
        init = create_perlin_noise([1.5**-i * 0.5 for i in range(12)], 1, 1, False)
        init2 = create_perlin_noise([1.5**-i * 0.5 for i in range(8)], 4, 4, False)
    elif perlin_mode == 'gray':
        init = create_perlin_noise([1.5**-i * 0.5 for i in range(12)], 1, 1, True)
        init2 = create_perlin_noise([1.5**-i * 0.5 for i in range(8)], 4, 4, True)
    else:
        init = create_perlin_noise([1.5**-i * 0.5 for i in range(12)], 1, 1, False)
        init2 = create_perlin_noise([1.5**-i * 0.5 for i in range(8)], 4, 4, True)
    init = TF.to_tensor(init).add(TF.to_tensor(init2)).div(2).to(device).unsqueeze(0).mul(2).sub(1)
    del init2
    return init.expand(batch_size, -1, -1, -1)


def read_image_workaround(path):
    """OpenCV reads images as BGR, Pillow saves them as RGB. Work around
    this incompatibility to avoid colour inversions."""
    im_tmp = cv2.imread(path)
    return cv2.cvtColor(im_tmp, cv2.COLOR_BGR2RGB)


def spherical_dist_loss(x, y):
    x = F.normalize(x, dim=-1)
    y = F.normalize(y, dim=-1)
    return (x - y).norm(dim=-1).div(2).arcsin().pow(2).mul(2)


def tv_loss(input):
    """L2 total variation loss, as in Mahendran et al."""
    input = F.pad(input, (0, 1, 0, 1), 'replicate')
    x_diff = input[..., :-1, 1:] - input[..., :-1, :-1]
    y_diff = input[..., 1:, :-1] - input[..., :-1, :-1]
    return (x_diff**2 + y_diff**2).mean([1, 2, 3])


def range_loss(input):
    return (input - input.clamp(-1, 1)).pow(2).mean([1, 2, 3])


def symm_loss_v(im, lpm):
    h = int(im.shape[3]/2)
    h1, h2 = im[:, :, :, :h], im[:, :, :, h:]
    h2 = TF.hflip(h2)
    return lpm(h1, h2)


def symm_loss_h(im, lpm):
    w = int(im.shape[2]/2)
    w1, w2 = im[:, :, :w, :], im[:, :, w:, :]
    w2 = TF.vflip(w2)
    return lpm(w1, w2)


stop_on_next_loop = False  # Make sure GPU memory doesn't get corrupted from cancelling the run mid-way through, allow a full frame to complete
scoreprompt = True
actual_total_steps = steps
actual_run_steps = 0


def do_run(batch_num, slice_num=-1):
    seed = args.seed
    for frame_num in range(args.start_frame, args.max_frames):
        if stop_on_next_loop:
            break

        # Inits if not video frames
        if args.animation_mode != "Video Input":
            if args.init_image == '':
                init_image = None
            else:
                init_image = args.init_image
            init_scale = args.init_scale
            skip_steps = args.skip_steps

        if args.animation_mode == "2D":
            if args.key_frames:
                angle = args.angle_series[frame_num]
                zoom = args.zoom_series[frame_num]
                translation_x = args.translation_x_series[frame_num]
                translation_y = args.translation_y_series[frame_num]
                print(f'angle: {angle}', f'zoom: {zoom}', f'translation_x: {translation_x}', f'translation_y: {translation_y}')

            if frame_num > 0:
                seed = seed + 1
                if resume_run and frame_num == start_frame:
                    img_0 = cv2.imread(batchFolder + f"/{batch_name}({batchNum})_{start_frame-1:04}.png")
                else:
                    img_0 = cv2.imread('prevFrame.png')
                center = (1 * img_0.shape[1] // 2, 1 * img_0.shape[0] // 2)
                trans_mat = np.float32([[1, 0, translation_x], [0, 1, translation_y]])
                rot_mat = cv2.getRotationMatrix2D(center, angle, zoom)
                trans_mat = np.vstack([trans_mat, [0, 0, 1]])
                rot_mat = np.vstack([rot_mat, [0, 0, 1]])
                transformation_matrix = np.matmul(rot_mat, trans_mat)
                img_0 = cv2.warpPerspective(img_0, transformation_matrix, (img_0.shape[1], img_0.shape[0]), borderMode=cv2.BORDER_WRAP)
                cv2.imwrite('prevFrameScaled.png', img_0)
                init_image = 'prevFrameScaled.png'
                init_scale = args.frames_scale
                skip_steps = args.calc_frames_skip_steps

        if args.animation_mode == "Video Input":
            seed = seed + 1
            init_image = f'{videoFramesFolder}/{frame_num+1:04}.jpg'
            init_scale = args.frames_scale
            skip_steps = args.calc_frames_skip_steps

        loss_values = []

        if seed is not None:
            np.random.seed(seed + batch_num)
            random.seed(seed + batch_num)
            torch.manual_seed(seed + batch_num)
            #torch.use_deterministic_algorithms(True, warn_only=True)
            # torch.cuda.manual_seed_all(seed)
            #torch.backends.cudnn.deterministic = True

        if args.cool_down >= 1:
            cooling_delay = round((args.cool_down / args.steps),2)
            print(f'Adding {args.cool_down} seconds of cool down time ({cooling_delay} per step)')
        
        # Use next prompt in series when doing a batch run
        if animation_mode == "None":
            frame_num = batch_num

        if frame_num == 0 or batch_num == 0:
            save_settings()

        if args.prompts_series is not None and frame_num >= len(
                args.prompts_series):
            frame_prompt = args.prompts_series[-1]
        elif args.prompts_series is not None:
            frame_prompt = args.prompts_series[frame_num]
        else:
            frame_prompt = []

        # TODO: Image prompts are being fetched on every cut for every model, which is quite slow.
        # We should get the image once and keep it in ram, reference it that way.
        if args.image_prompts_series is not None and frame_num >= len(
                args.image_prompts_series):
            image_prompt = args.image_prompts_series[-1]
        elif args.image_prompts_series is not None:
            image_prompt = args.image_prompts_series[frame_num]
        else:
            image_prompt = []

        if (type(frame_prompt) is list):
            frame_prompt = {0: frame_prompt}

        if (type(image_prompt) is list):
            image_prompt = {0: image_prompt}

        prev_sample_prompt = []
        prev_sample_image_prompt = []

        def do_weights(s, clip_managers):
            nonlocal prev_sample_prompt
            nonlocal prev_sample_image_prompt
            sample_prompt = []
            sample_image_prompt = []

            print_sample_prompt = False
            if (s not in frame_prompt.keys()):
                sample_prompt = prev_sample_prompt.copy()
            else:
                print_sample_prompt = True
                sample_prompt = frame_prompt[s].copy()
                prev_sample_prompt = sample_prompt.copy()

            if print_sample_prompt:
                print(f'\nPrompt for step {s}: {sample_prompt}')

            print_sample_image_prompt = False
            if (s not in image_prompt.keys()):
                sample_image_prompt = prev_sample_image_prompt.copy()
            else:
                print_sample_image_prompt = True
                sample_image_prompt = image_prompt[s].copy()
                prev_sample_image_prompt = sample_image_prompt.copy()

            if print_sample_image_prompt and len(sample_image_prompt) != 0:
                print(f'\nImage prompt for step {s}: {sample_image_prompt}')

            for clip_manager in clip_managers:
                # We should probably let the clip_manager manage its own state
                # but do this for now.
                if sample_prompt and print_sample_prompt: # only need to do this if the prompt has changed
                    prompt_embeds, prompt_weights = clip_manager.embed_text_prompts(
                        prompts=sample_prompt,
                        step=s,
                        fuzzy_prompt=args.fuzzy_prompt,
                        fuzzy_prompt_rand_mag=args.rand_mag
                    )
                    clip_manager.prompt_embeds = prompt_embeds
                    clip_manager.prompt_weights = prompt_weights
                if sample_image_prompt and print_sample_image_prompt: # only need to do this if the prompt has changed
                    img_prompt_embeds, img_prompt_weights = clip_manager.embed_image_prompts(
                        prompts=sample_image_prompt,
                        step=s,
                        cutn=16,
                        cut_model=MakeCutoutsDango,
                        side_x=side_x,
                        side_y=side_y,
                        fuzzy_prompt=args.fuzzy_prompt,
                        fuzzy_prompt_rand_mag=args.rand_mag,
                        cutout_skip_augs=args.skip_augs
                    )
                    if clip_manager.prompt_embeds is not None:
                        clip_manager.prompt_embeds = torch.cat([img_prompt_embeds, clip_manager.prompt_embeds])
                    else:
                        clip_manager.prompt_embeds = img_prompt_embeds
                    if clip_manager.prompt_weights is not None:
                        clip_manager.prompt_weights = torch.cat([img_prompt_weights, clip_manager.prompt_weights])
                    else:
                        clip_manager.prompt_weights = img_prompt_weights
                if not any((sample_prompt, image_prompts)):
                    raise RuntimeError("No prompts provided. You must provide text_prompts and/or image_prompts.")

                if clip_manager.prompt_weights.sum().abs() < 1e-3:
                    raise RuntimeError('The weights must not sum to 0.')
                clip_manager.prompt_weights /= clip_manager.prompt_weights.sum().abs()

        initial_weights = False

        print(f'Skipping {skip_steps} steps')

        if (skip_steps > 0):
            for i in range(skip_steps, 0, -1):
                if (str(i) in frame_prompt.keys()):
                    do_weights(i, clip_managers)
                    initial_weights = True
                    break

        # if no init_masked is provided, we make one with the render mask
        def make_masked_init(image, mask):
            image = np.array(image)
            image = image.astype(np.float32)/255.0
            image = image[None].transpose(0,3,1,2)
            image = torch.from_numpy(image)

            mask = np.array(mask)
            mask = mask.astype(np.float32)/255.0
            mask = mask[None,None]
            mask = torch.from_numpy(mask)

            masked_image = (0+mask)*image
            return masked_image

        if (not initial_weights):
            do_weights(0, clip_managers)

        #Init Image stuff:
        #init is ultimately what we render against
        #init_image is the image to use to start with, unless we have init_masked, in which case we just store init_image
        #init_masked is a secondary init image with data only where we want to render (can be perlin instead, see below)
        #render_mask is tells us what part of the render to keep (white) and what part to restore from init_image
        #TODO: consider how this is affected by gobig
        init = None
        if init_image is not None:
            init_img = Image.open(fetch(init_image)).convert('RGB')
            init_img = init_img.resize((args.side_x, args.side_y), get_resampling_mode())
            if init_masked is not None:
                init_masked_img = Image.open(fetch(init_masked)).convert('RGB')
                init = TF.to_tensor(init_masked_img).to(device).unsqueeze(0).mul(2).sub(1)
            else:
                init = TF.to_tensor(init_img).to(device).unsqueeze(0).mul(2).sub(1)
            init_img = init_img.convert('RGBA') # now that we've made our init, we add an alpha channel for later compositing

        rmask = None
        if render_mask is not None:
            rmask_img = Image.open(fetch(render_mask)).convert('L')
            rmask_img = rmask_img.resize((args.side_x, args.side_y), get_resampling_mode())
            rmask = TF.to_tensor(rmask_img).to(device).unsqueeze(0)
            if init_masked is None:
                init = gen_perlin()
                init = TF.to_pil_image(init.clamp(0, 1).squeeze())
                init_mask = make_masked_init(init, rmask_img).to(device)
                init_mask = TF.to_pil_image(init_mask.clamp(0, 1).squeeze())
                init = TF.to_tensor(init_mask).to(device).unsqueeze(0).mul(2).sub(1)
                #init_mask.save('init_mask.png')

        if (args.perlin_init == True) and (init_image == None):
            init = gen_perlin()

        cur_t = None

        def cond_fn(x, t, y=None):
            with torch.enable_grad():
                x_is_NaN = False
                x = x.detach().requires_grad_()
                n = x.shape[0]
                if use_secondary_model is True:
                    alpha = torch.tensor(diffusion.sqrt_alphas_cumprod[cur_t], device=device, dtype=torch.float32)
                    sigma = torch.tensor(diffusion.sqrt_one_minus_alphas_cumprod[cur_t], device=device, dtype=torch.float32)
                    cosine_t = alpha_sigma_to_t(alpha, sigma)
                    out = secondary_model(x, cosine_t[None].repeat([n])).pred
                    fac = diffusion.sqrt_one_minus_alphas_cumprod[cur_t]
                    x_in = out * fac + x * (1 - fac)
                    x_in_grad = torch.zeros_like(x_in)
                else:
                    my_t = torch.ones([n], device=device, dtype=torch.long) * cur_t
                    out = diffusion.p_mean_variance(model,  x, my_t, clip_denoised=False, model_kwargs={'y': y})
                    fac = diffusion.sqrt_one_minus_alphas_cumprod[cur_t]
                    x_in = out['pred_xstart'] * fac + x * (1 - fac)
                    x_in_grad = torch.zeros_like(x_in)

                for clip_manager in clip_managers:
                    t_int = int(t.item()) + 1
                    for _ in range(args.cutn_batches[1000 - t_int]):
                        clip_losses = clip_manager.get_cut_batch_losses(
                            x_in,
                            n,
                            args.cut_overview,
                            args.cut_innercut,
                            args.cut_ic_pow,
                            args.cut_icgray_p,
                            t_int,
                            MakeCutoutsDango,
                            cl_args.cut_debug
                        )
                        loss_values.append(clip_losses.sum().item())  # log loss, probably shouldn't do per cutn_batch
                        #factor in render_mask
                        prompt_grad = torch.autograd.grad(clip_losses.sum() * args.clip_guidance_scale[1000 - t_int], x_in)[0] / args.cutn_batches[1000 - t_int]
                        if rmask != None:
                            x_in_grad += rmask.mul(prompt_grad)
                        else:
                            x_in_grad += prompt_grad

                tv_losses = tv_loss(x_in)
                if use_secondary_model is True:
                    range_losses = range_loss(out)
                else:
                    range_losses = range_loss(out['pred_xstart'])
                sat_losses = torch.abs(x_in - x_in.clamp(min=-1, max=1)).mean()
                logger.debug(f"tv_loss: {tv_losses.sum()}")
                logger.debug(f"range_loss: {range_losses.sum()}")
                logger.debug(f"sat_loss: {sat_losses.sum()}")
                loss = tv_losses.sum() * tv_scale + range_losses.sum() * range_scale + sat_losses.sum() * sat_scale
                if init is not None and args.init_scale:
                    init_losses = lpips_model(x_in, init)
                    loss = loss + init_losses.sum() * args.init_scale
                if args.symmetry_loss_v and actual_run_steps <= args.symm_switch:
                    sloss = symm_loss_v(x_in, lpips_model)
                    loss = loss + sloss.sum() * args.symm_loss_scale[1000 - t_int]
                if args.symmetry_loss_h and actual_run_steps <= args.symm_switch:
                    sloss = symm_loss_h(x_in, lpips_model)
                    loss = loss + sloss.sum() * args.symm_loss_scale[1000 - t_int]
                x_in_grad += torch.autograd.grad(loss, x_in)[0]
                if torch.isnan(x_in_grad).any() == False:
                    grad = -torch.autograd.grad(x_in, x, x_in_grad)[0]
                else:
                    # print("NaN'd")
                    x_is_NaN = True
                    grad = torch.zeros_like(x)
            if args.clamp_grad and x_is_NaN == False:
                magnitude = grad.square().mean().sqrt()

                return grad * magnitude.clamp(max=args.clamp_max[1000 - t_int]) / magnitude
            return grad

        if args.sampling_mode == 'ddim':
            sample_fn = diffusion.ddim_sample_loop_progressive
        else:
            sample_fn = diffusion.plms_sample_loop_progressive

        progressBar = tqdm(range(steps), initial=args.skip_steps)
        starting_init = init
        # the actual image gen
        gc.collect()
        if "cuda" in str(device):
            with torch.cuda.device(device):
                torch.cuda.empty_cache()
        cur_t = diffusion.num_timesteps - skip_steps - 1
        global actual_total_steps
        global actual_run_steps
        actual_run_steps = skip_steps
        total_steps = cur_t
        logger.debug(f'cur_t at start of image is {cur_t} and diffusion.num_timesteps is {diffusion.num_timesteps}')

        if (args.perlin_init == True) and (init_image == None):
            init = gen_perlin()
        else:
            init = starting_init  # make sure we return to a baseline for each image in a batch

        def do_sample_fn(_init_image, _skip):
            if args.sampling_mode == 'ddim':
                samples = sample_fn(
                    model,
                    (batch_size, 3, args.side_y, args.side_x),
                    clip_denoised=clip_denoised,
                    model_kwargs={},
                    cond_fn=cond_fn,
                    progress=False,
                    skip_timesteps=_skip,
                    init_image=init,
                    randomize_class=randomize_class,
                    eta=eta,
                )
            else:
                samples = sample_fn(
                    model,
                    (batch_size, 3, args.side_y, args.side_x),
                    clip_denoised=clip_denoised,
                    model_kwargs={},
                    cond_fn=cond_fn,
                    progress=False,
                    skip_timesteps=_skip,
                    init_image=init,
                    randomize_class=randomize_class,
                    order=2,
                )

            return samples

        imgToSharpen = None
        adjustment_prompt = []
        do_samples = True
        if slice_num >= 0:
            progressBar.set_description(f'Slice {slice_num} of {slices_todo}: ')
        else:
            progressBar.set_description(f'Image {batch_num + 1} of {n_batches}: ')
        while cur_t >= stop_early:
            if do_samples == True:
                samples = do_sample_fn(init, steps - cur_t - 1)
                do_samples = False
            for j, sample in enumerate(samples):
                actual_run_steps += 1
                if args.cool_down >= 1:
                    time.sleep(cooling_delay)
                progressBar.n = actual_run_steps
                progressBar.refresh()
                cur_t -= 1
                if (cur_t < stop_early):
                    cur_t = -1

                intermediateStep = False
                if actual_run_steps in args.intermediate_saves:
                    intermediateStep = True

                if actual_run_steps % args.display_rate == 0 or cur_t == -1 or intermediateStep == True:
                    for k, image in enumerate(sample['pred_xstart']):
                        current_time = datetime.now().strftime('%y%m%d-%H%M%S_%f')
                        percent = math.ceil(actual_run_steps / actual_total_steps * 100)
                        if args.n_batches > 0:
                            # if intermediates are saved to the subfolder, don't append a step or percentage to the name
                            if cur_t == -1 and args.intermediates_in_subfolder is True:
                                if animation_mode != "None":
                                    save_num = f'{frame_num:04}'
                                else:
                                    if slice_num >= 0:
                                        save_num = 'slice_' + str(slice_num)
                                    else:
                                        save_num = batch_num
                                filename = f'{args.batch_name}_{args.batchNum}_{save_num}.png'
                            else:
                                filename = f'{args.batch_name}({args.batchNum})_{batch_num:04}-{actual_run_steps:03}.png'
                        image = TF.to_pil_image(image.add(1).div(2).clamp(0, 1))
                        # add some key metadata to the PNG if the commandline allows it
                        metadata = PngInfo()
                        if add_metadata == True:
                            metadata.add_text("prompt", str(text_prompts))
                            metadata.add_text("seed", str(seed))
                            metadata.add_text("steps", str(steps))
                            metadata.add_text("init_image", str(init_image_OriginalPath))
                            metadata.add_text("skip_steps", str(skip_steps))
                            metadata.add_text("clip_guidance_scale", str(clip_guidance_scale))
                            metadata.add_text("tv_scale", str(tv_scale))
                            metadata.add_text("range_scale", str(range_scale))
                            metadata.add_text("sat_scale", str(sat_scale))
                            metadata.add_text("eta", str(eta))
                            metadata.add_text("clamp_max", str(clamp_max))
                            metadata.add_text("cut_overview", str(cut_overview))
                            metadata.add_text("cut_innercut", str(cut_innercut))
                            metadata.add_text("cut_ic_pow", str(og_cut_ic_pow))

                        output_quality = 100
                        if use_jpg:
                            filename = filename.replace('.png','.jpg')
                            output_quality = 95
                        
                        if actual_run_steps % args.display_rate == 0 or actual_run_steps == 1 or cur_t == -1:
                            if cl_args.cuda != '0':
                                image.save(f"progress{cl_args.cuda}.png")  # note the GPU being used if it's not 0, so it won't overwrite other GPU's work
                            else:
                                image.save('progress.png')
                        if actual_run_steps in args.intermediate_saves:
                            if args.intermediates_in_subfolder is True:
                                image.save(f'{partialFolder}/{filename}', quality = output_quality)
                            else:
                                image.save(f'{batchFolder}/{filename}', quality = output_quality)
                            if geninit is True:
                                image.save('geninit.png')
                                raise KeyboardInterrupt

                        if cur_t == -1:
                            if args.animation_mode != "None":
                                image.save('prevFrame.png')
                            if args.sharpen_preset != "Off" and animation_mode == "None":
                                imgToSharpen = image
                                if args.keep_unsharp is True:
                                    image.save(f'{unsharpenFolder}/{filename}', quality = output_quality)
                            else:
                                if render_mask:
                                    # I don't know why PILLOW has to have copies of things, but it does. 
                                    print('\nUsing render mask to composite rendered image with init image.')
                                    image2 = image.copy()
                                    image2.putalpha(rmask_img)
                                    #image2.save('test.png')
                                    image3 = image2.copy()
                                    image3 = Image.alpha_composite(init_img, image3)
                                    image = image3.copy()
                                    image.save('progress.png')
                                image.save(f'{batchFolder}/{filename}', pnginfo=metadata, quality = output_quality)
                                if cl_args.esrgan:
                                    print('Resizing with ESRGAN')
                                    try:
                                        gc.collect()
                                        if "cuda" in str(device):
                                            with torch.cuda.device(device):
                                                torch.cuda.empty_cache()
                                        subprocess.run(
                                            ['realesrgan-ncnn-vulkan', '-i', f'{batchFolder}/{filename}', '-o', f'{batchFolder}/ESRGAN-{filename}'],
                                            stdout=subprocess.PIPE
                                        ).stdout.decode('utf-8')
                                    except Exception as e:
                                        print('ESRGAN resize failed. Make sure realesrgan-ncnn-vulkan is in your path (or in this directory)')
                                        print(e)

                            if (batch_num + 1) < args.n_batches:
                                progressBar.write(f'Image finished! Using seed {seed + batch_num + 1} for next image.')
                            else:
                                progressBar.write(f'Image finished!')

                    #is this do_weights needed?
                    #do_weights(steps - cur_t - 1, clip_managers)

                do_weights(steps - cur_t - 1, clip_managers)

                def get_sample_as_image(sample):
                    image = sample['pred_xstart'][0]
                    image = TF.to_pil_image(image.add(1).div(2).clamp(0, 1))
                    return image

                s = steps - cur_t

                # BRIGHTNESS and CONTRAST automatic correction
                if (s % adjustment_interval == 0) and (s < (steps * .3)) and (fix_brightness_contrast == True):
                    image = get_sample_as_image(sample)
                    stat = ImageStat.Stat(image)
                    brightness = sum(stat.mean) / len(stat.mean)
                    contrast = sum(stat.stddev) / len(stat.stddev)
                    if (high_brightness_adjust and s > high_brightness_start and brightness > high_brightness_threshold):
                        progressBar.write(f"High brightness corrected at step {s}")
                        filter = ImageEnhance.Brightness(image)
                        image = filter.enhance(high_brightness_adjust_amount)
                        init = TF.to_tensor(image).to(device).unsqueeze(0).mul(2).sub(1)
                        do_samples = True
                        break

                    if (low_brightness_adjust and s > low_brightness_start and brightness < low_brightness_threshold):
                        progressBar.write(f"Low brightness corrected at step {s}")
                        filter = ImageEnhance.Brightness(image)
                        image = filter.enhance(low_brightness_adjust_amount)
                        init = TF.to_tensor(image).to(device).unsqueeze(0).mul(2).sub(1)
                        do_samples = True
                        break

                    if (high_contrast_adjust and s > high_contrast_start and contrast > high_contrast_threshold):
                        progressBar.write(f"High contrast corrected at step {s}")
                        filter = ImageEnhance.Contrast(image)
                        image = filter.enhance(high_contrast_adjust_amount)
                        init = TF.to_tensor(image).to(device).unsqueeze(0).mul(2).sub(1)
                        do_samples = True
                        break

                    if (low_contrast_adjust and s > low_contrast_start and contrast < low_contrast_threshold):
                        progressBar.write(f"Low contrast corrected at step {s}")
                        filter = ImageEnhance.Contrast(image)
                        image = filter.enhance(low_contrast_adjust_amount)
                        init = TF.to_tensor(image).to(device).unsqueeze(0).mul(2).sub(1)
                        do_samples = True
                        break

                # A simpler version of symmetry that just mirrors half the current image and uses it as an init
                if (actual_run_steps in args.simple_symmetry) and ((args.symmetry_loss_v == False) and (args.symmetry_loss_h == False)):
                    image = get_sample_as_image(sample)
                    progressBar.write(f"Performing simple symmetry at step {s}")
                    left_image = image.crop((0,0,(int(side_x / 2)), side_y))
                    right_image = left_image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    image.paste(right_image, ((int(side_x / 2)), 0))
                    init = TF.to_tensor(image).to(device).unsqueeze(0).mul(2).sub(1)
                    #sample['pred_xstart'][0] = TF.to_tensor(image).to(device).unsqueeze(0).mul(2).sub(1) -- this didn't work at all
                    do_samples = True
                    break

                if (cur_t == -1):
                    break
        progressBar.close()            


def save_settings():
    setting_list = {
        'batch_name': batch_name,
        'text_prompts': text_prompts,
        'n_batches': n_batches,
        'steps': steps,
        'display_rate': display_rate,
        'width_height_scale': width_height_scale,
        'width': int(width_height[0] / width_height_scale),
        'height': int(width_height[1] / width_height_scale),
        'set_seed': seed,
        'image_prompts': image_prompts,
        'clip_guidance_scale': clip_guidance_scale,
        'tv_scale': tv_scale,
        'range_scale': range_scale,
        'sat_scale': sat_scale,
        # 'cutn': cutn,
        'cutn_batches': og_cutn_batches,
        'cutn_batches_final': cutn_batches_final,
        'max_frames': max_frames,
        'interp_spline': interp_spline,
        # 'rotation_per_frame': rotation_per_frame,
        'init_image': init_image,
        'init_masked': init_masked,
        'render_mask': render_mask,
        'init_scale': init_scale,
        'skip_steps': skip_steps,
        'skip_steps_ratio': skip_steps_ratio,
        # 'zoom_per_frame': zoom_per_frame,
        'frames_scale': frames_scale,
        'frames_skip_steps': frames_skip_steps,
        'perlin_init': perlin_init,
        'perlin_mode': perlin_mode,
        'skip_augs': skip_augs,
        'randomize_class': randomize_class,
        'clip_denoised': clip_denoised,
        'clamp_grad': clamp_grad,
        'clamp_max': clamp_max,
        'fuzzy_prompt': fuzzy_prompt,
        'rand_mag': rand_mag,
        'eta': eta,
        'diffusion_model': diffusion_model.name,
        'use_secondary_model': use_secondary_model,
        'diffusion_steps': diffusion_steps,
        'sampling_mode': sampling_mode,
        'ViTB32': ViTB32,
        'ViTB16': ViTB16,
        'ViTL14': ViTL14,
        'ViTL14_336': ViTL14_336,
        'RN101': RN101,
        'RN50': RN50,
        'RN50x4': RN50x4,
        'RN50x16': RN50x16,
        'RN50x64': RN50x64,
        'ViTB32_laion2b_e16': ViTB32_laion2b_e16,
        'ViTB32_laion400m_e31': ViTB32_laion400m_e31,
        'ViTB32_laion400m_32': ViTB32_laion400m_32,
        'ViTB32quickgelu_laion400m_e31': ViTB32quickgelu_laion400m_e31,
        'ViTB32quickgelu_laion400m_e32': ViTB32quickgelu_laion400m_e32,
        'ViTB16_laion400m_e31': ViTB16_laion400m_e31,
        'ViTB16_laion400m_e32': ViTB16_laion400m_e32,
        'RN50_yffcc15m': RN50_yffcc15m,
        'RN50_cc12m': RN50_cc12m,
        'RN50_quickgelu_yfcc15m': RN50_quickgelu_yfcc15m,
        'RN50_quickgelu_cc12m': RN50_quickgelu_cc12m,
        'RN101_yfcc15m': RN101_yfcc15m,
        'RN101_quickgelu_yfcc15m': RN101_quickgelu_yfcc15m,
        'cut_overview': str(cut_overview),
        'cut_innercut': str(cut_innercut),
        'cut_ic_pow': og_cut_ic_pow,
        'cut_ic_pow_final': cut_ic_pow_final,
        'cut_icgray_p': str(cut_icgray_p),
        'cut_heatmaps': cut_heatmaps,
        'smooth_schedules': smooth_schedules,
        'animation_mode': animation_mode,
        'key_frames': key_frames,
        'angle': angle,
        'zoom': zoom,
        'translation_x': translation_x,
        'translation_y': translation_y,
        'video_init_path': video_init_path,
        'extract_nth_frame': extract_nth_frame,
        'stop_early': stop_early,
        'fix_brightness_contrast': fix_brightness_contrast,
        'sharpen_preset': sharpen_preset,
        'keep_unsharp': keep_unsharp,
        'gobig_scale': gobig_scale,
        'gobig_skip_ratio': gobig_skip_ratio,
        'gobig_overlap': gobig_overlap,
        'symmetry_loss_v': symmetry_loss_v,
        'symmetry_loss_h': symmetry_loss_h,
        'symm_loss_scale': symm_loss_scale,
        'symm_switch': symm_switch,
        'simple_symmetry': simple_symmetry,
        'perlin_brightness': perlin_brightness,
        'perlin_contrast': perlin_contrast,
        'use_jpg': use_jpg
    }
    with open(f"{batchFolder}/{batch_name}_{batchNum}_settings.json",  "w+", encoding="utf-8") as f:  # save settings
        json.dump(setting_list, f, ensure_ascii=False, indent=4)


# @title 2.3 Define the secondary diffusion model


def append_dims(x, n):
    return x[(Ellipsis, *(None, ) * (n - x.ndim))]


def expand_to_planes(x, shape):
    return append_dims(x, len(shape)).repeat([1, 1, *shape[2:]])


def alpha_sigma_to_t(alpha, sigma):
    return torch.atan2(sigma, alpha) * 2 / math.pi


def t_to_alpha_sigma(t):
    return torch.cos(t * math.pi / 2), torch.sin(t * math.pi / 2)


@dataclass
class DiffusionOutput:
    v: torch.Tensor
    pred: torch.Tensor
    eps: torch.Tensor


class ConvBlock(nn.Sequential):
    def __init__(self, c_in, c_out):
        super().__init__(nn.Conv2d(c_in, c_out, 3, padding=1),  nn.ReLU(inplace=True))


class SkipBlock(nn.Module):
    def __init__(self, main, skip=None):
        super().__init__()
        self.main = nn.Sequential(*main)
        self.skip = skip if skip else nn.Identity()

    def forward(self, input):
        return torch.cat([self.main(input), self.skip(input)], dim=1)


class FourierFeatures(nn.Module):
    def __init__(self, in_features, out_features, std=1.):
        super().__init__()
        assert out_features % 2 == 0
        self.weight = nn.Parameter(torch.randn([out_features // 2, in_features]) * std)

    def forward(self, input):
        f = 2 * math.pi * input @ self.weight.T
        return torch.cat([f.cos(), f.sin()], dim=-1)


class SecondaryDiffusionImageNet(nn.Module):
    def __init__(self):
        super().__init__()
        c = 64  # The base channel count

        self.timestep_embed = FourierFeatures(1, 16)

        self.net = nn.Sequential(
            ConvBlock(3 + 16, c),
            ConvBlock(c, c),
            SkipBlock([
                nn.AvgPool2d(2),
                ConvBlock(c, c * 2),
                ConvBlock(c * 2, c * 2),
                SkipBlock([
                    nn.AvgPool2d(2),
                    ConvBlock(c * 2, c * 4),
                    ConvBlock(c * 4, c * 4),
                    SkipBlock([
                        nn.AvgPool2d(2),
                        ConvBlock(c * 4, c * 8),
                        ConvBlock(c * 8, c * 4),
                        nn.Upsample(scale_factor=2,
                                    mode='bilinear',
                                    align_corners=False),
                    ]),
                    ConvBlock(c * 8, c * 4),
                    ConvBlock(c * 4, c * 2),
                    nn.Upsample(scale_factor=2,
                                mode='bilinear',
                                align_corners=False),
                ]),
                ConvBlock(c * 4, c * 2),
                ConvBlock(c * 2, c),
                nn.Upsample(scale_factor=2,
                            mode='bilinear',
                            align_corners=False),
            ]),
            ConvBlock(c * 2, c),
            nn.Conv2d(c, 3, 3, padding=1),
        )

    def forward(self, input, t):
        timestep_embed = expand_to_planes(self.timestep_embed(t[:, None]), input.shape)
        v = self.net(torch.cat([input, timestep_embed], dim=1))
        alphas, sigmas = map(partial(append_dims, n=v.ndim), t_to_alpha_sigma(t))
        pred = input * alphas - v * sigmas
        eps = input * sigmas + v * alphas
        return DiffusionOutput(v, pred, eps)


class SecondaryDiffusionImageNet2(nn.Module):
    def __init__(self):
        super().__init__()
        c = 64  # The base channel count
        cs = [c, c * 2, c * 2, c * 4, c * 4, c * 8]

        self.timestep_embed = FourierFeatures(1, 16)
        self.down = nn.AvgPool2d(2)
        self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)

        self.net = nn.Sequential(
            ConvBlock(3 + 16, cs[0]),
            ConvBlock(cs[0], cs[0]),
            SkipBlock([
                self.down,
                ConvBlock(cs[0], cs[1]),
                ConvBlock(cs[1], cs[1]),
                SkipBlock([
                    self.down,
                    ConvBlock(cs[1], cs[2]),
                    ConvBlock(cs[2], cs[2]),
                    SkipBlock([
                        self.down,
                        ConvBlock(cs[2], cs[3]),
                        ConvBlock(cs[3], cs[3]),
                        SkipBlock([
                            self.down,
                            ConvBlock(cs[3], cs[4]),
                            ConvBlock(cs[4], cs[4]),
                            SkipBlock([
                                self.down,
                                ConvBlock(cs[4], cs[5]),
                                ConvBlock(cs[5], cs[5]),
                                ConvBlock(cs[5], cs[5]),
                                ConvBlock(cs[5], cs[4]),
                                self.up,
                            ]),
                            ConvBlock(cs[4] * 2, cs[4]),
                            ConvBlock(cs[4], cs[3]),
                            self.up,
                        ]),
                        ConvBlock(cs[3] * 2, cs[3]),
                        ConvBlock(cs[3], cs[2]),
                        self.up,
                    ]),
                    ConvBlock(cs[2] * 2, cs[2]),
                    ConvBlock(cs[2], cs[1]),
                    self.up,
                ]),
                ConvBlock(cs[1] * 2, cs[1]),
                ConvBlock(cs[1], cs[0]),
                self.up,
            ]),
            ConvBlock(cs[0] * 2, cs[0]),
            nn.Conv2d(cs[0], 3, 3, padding=1),
        )

    def forward(self, input, t):
        timestep_embed = expand_to_planes(self.timestep_embed(t[:, None]), input.shape)
        v = self.net(torch.cat([input, timestep_embed], dim=1))
        alphas, sigmas = map(partial(append_dims, n=v.ndim),  t_to_alpha_sigma(t))
        pred = input * alphas - v * sigmas
        eps = input * sigmas + v * alphas
        return DiffusionOutput(v, pred, eps)


timestep_respacing = '50'  # param ['25','50','100','150','250','500','1000','ddim25','ddim50', 'ddim75', 'ddim100','ddim150','ddim250','ddim500','ddim1000']
use_checkpoint = True  # @param {type: 'boolean'}
other_sampling_mode = 'bicubic'
# @markdown If you're having issues with model downloads, check this to compare SHA's:
check_model_SHA = False  # @param{type:"boolean"}

# TODO: Chance this to use any available model in the JSON file
if diffusion_model == 'random':
    the_models = [
        '256x256_diffusion_uncond',
        '512x512_diffusion_uncond_finetune_008100',
        '256x256_openai_comics_faces_by_alex_spirin',
        'pixel_art_diffusion_hard_256',
        'pixel_art_diffusion_soft_256',
        'portrait_generator_v001',
        'pixelartdiffusion4k',
        'watercolordiffusion',
        'watercolordiffusion_2',
        'PulpSciFiDiffusion',
        'FeiArt_Handpainted_CG_Diffusion',
        'IsometricDiffusionRevrart512px'
    ]
    diffusion_model = random.choice(the_models)
    print(f'Random model selected is {diffusion_model}')


@dataclass
class Diff_Model:
    def __init__(self):
        pass
    name: str
    SHA: str
    plink: str
    path: str
    attention_resolutions: str
    class_cond: bool
    rescale_timesteps: bool
    image_size: int
    learn_sigma: bool
    noise_schedule: str
    num_channels: int
    num_res_blocks: int
    resblock_updown: bool
    use_scale_shift_norm: bool
    timestep_respacing: str
    use_fp16: bool
    num_head_channels: int = -1
    num_heads: int = 1
    slink: str = "none"


try:
    with open('diffusion_models.json', 'r', encoding="utf-8") as json_file:
        print(f'Loading diffusion model details from diffusion_models.json')
        user_supplied_name = diffusion_model
        print(f'Using Diffusion Model: {user_supplied_name}')
        diffusion_models_file = json.load(json_file)
        if user_supplied_name in diffusion_models_file:
            diffusion_model = Diff_Model()
            diffusion_model.name = user_supplied_name
            diffusion_model.SHA = diffusion_models_file[user_supplied_name]['SHA']
            diffusion_model.plink = diffusion_models_file[user_supplied_name]['primary_link']
            if is_json_key_present(settings_file, user_supplied_name, 'secondary_link'):
                diffusion_model.slink = diffusion_models_file[user_supplied_name]['secondary_link']
            diffusion_model.path = diffusion_models_file[user_supplied_name]['file_name']
            diffusion_model.attention_resolutions = diffusion_models_file[user_supplied_name]['attention_resolutions']
            diffusion_model.class_cond = diffusion_models_file[user_supplied_name]['class_cond']
            diffusion_model.rescale_timesteps = diffusion_models_file[user_supplied_name]['rescale_timesteps']
            diffusion_model.image_size = diffusion_models_file[user_supplied_name]['image_size']
            diffusion_model.learn_sigma = diffusion_models_file[user_supplied_name]['learn_sigma']
            diffusion_model.noise_schedule = diffusion_models_file[user_supplied_name]['noise_schedule']
            diffusion_model.num_channels = diffusion_models_file[user_supplied_name]['num_channels']
            if is_json_key_present(diffusion_models_file, user_supplied_name, 'num_head_channels'):
                diffusion_model.num_head_channels = diffusion_models_file[user_supplied_name]['num_head_channels']
            diffusion_model.num_heads = diffusion_models_file[user_supplied_name]['num_heads']
            diffusion_model.num_res_blocks = diffusion_models_file[user_supplied_name]['num_res_blocks']
            diffusion_model.resblock_updown = diffusion_models_file[user_supplied_name]['resblock_updown']
            diffusion_model.use_scale_shift_norm = diffusion_models_file[user_supplied_name]['use_scale_shift_norm']
            if is_json_key_present(diffusion_models_file, user_supplied_name, 'use_fp16'):
                if fp16_mode == True:
                    diffusion_model.use_fp16 = diffusion_models_file[user_supplied_name]['use_fp16']
                else:
                    diffusion_model.use_fp16 = False # Can't use fp16 when in CPU mode
            if is_json_key_present(diffusion_models_file, user_supplied_name, 'timestep_respacing'):
                diffusion_model.timestep_respacing = diffusion_models_file[user_supplied_name]['timestep_respacing']
            else:
                diffusion_model.timestep_respacing = timestep_respacing
except Exception as e:
    print('Unable to read diffusion_models.json - check formatting')
    print(e)
    quit()


def download_models(diffusion_model, use_secondary_model):
    model_downloaded = False
    model_secondary_downloaded = False
    model_file = f'{model_path}/{diffusion_model.path}'
    model_secondary_SHA = '983e3de6f95c88c81b2ca7ebb2c217933be1973b1ff058776b970f901584613a'
    model_secondary_link = 'https://the-eye.eu/public/AI/models/v-diffusion/secondary_model_imagenet_2.pth'
    model_secondary_link_fb = 'https://www.dropbox.com/s/luv4fezod3r8d2n/secondary_model_imagenet_2.pth'
    model_secondary_path = f'{model_path}/secondary_model_imagenet_2.pth'

    if os.path.exists(model_file):
        model_downloaded = True
        if check_model_SHA:
            print(f'Checking SHA for {diffusion_model.name}')
            with open(model_file, "rb") as f:
                bytes = f.read()
                hash = hashlib.sha256(bytes).hexdigest()
            if hash != diffusion_model.SHA:
                print('SHA does not match. Redownloading...')
                model_downloaded = False

    if model_downloaded == False:
        print(f'{diffusion_model.name} Model downloading. This may take a while...')
        urllib.request.urlretrieve(diffusion_model.plink, model_file)
        if os.path.exists(model_file):
            model_downloaded = True
        else:
            print('First URL failed, using backup if available')
            if diffusion_model.slink != "none":
                urllib.request.urlretrieve(diffusion_model.slink, model_file)
            if os.path.exists(model_file):
                model_downloaded = True

    if model_downloaded == False:
        print('Unable to download the diffusion model.')
        print('Please check your diffusion_models.json file for proper formatting,')
        print('Or check the Prog Rock Diffusion github for updated links.')
        quit()

    if os.path.exists(model_secondary_path):
        model_secondary_downloaded = True
        if check_model_SHA:
            print(f'Checking SHA for Secondary Model')
            with open(model_secondary_path, "rb") as f:
                bytes = f.read()
                hash = hashlib.sha256(bytes).hexdigest()
            if hash != model_secondary_SHA:
                print('SHA does not match. Redownloading...')
                model_secondary_downloaded = False

    if model_secondary_downloaded == False:
        print(f'Secondary Model downloading. This may take a while...')
        urllib.request.urlretrieve(model_secondary_link, model_secondary_path)
        if os.path.exists(model_secondary_path):
            model_secondary_downloaded = True
        else:
            print('First URL failed, using backup if available')
            urllib.request.urlretrieve(model_secondary_link_fb, model_secondary_path)
            if os.path.exists(model_secondary_path):
                model_secondary_downloaded = True

    if model_secondary_downloaded == False:
        print('Unable to download the secondary diffusion model.')
        print('Please check the Prog Rock Diffusion github for a possible updated version with new links.')
        quit()


download_models(diffusion_model, use_secondary_model)

model_config = model_and_diffusion_defaults()
model_config.update({
    'attention_resolutions': diffusion_model.attention_resolutions,
    'class_cond': diffusion_model.class_cond,
    'diffusion_steps': diffusion_steps,
    'rescale_timesteps': diffusion_model.rescale_timesteps,
    'timestep_respacing': diffusion_model.timestep_respacing,
    'image_size': diffusion_model.image_size,
    'learn_sigma': diffusion_model.learn_sigma,
    'noise_schedule': diffusion_model.noise_schedule,
    'num_channels': diffusion_model.num_channels,
    'num_head_channels': diffusion_model.num_head_channels,
    'num_heads': diffusion_model.num_heads,
    'num_res_blocks': diffusion_model.num_res_blocks,
    'resblock_updown': diffusion_model.resblock_updown,
    'use_checkpoint': use_checkpoint,
    'use_fp16': diffusion_model.use_fp16,
    'use_scale_shift_norm': diffusion_model.use_scale_shift_norm,
})

model_default = model_config['image_size']

def load_secondary_model():
    with track_model_vram(device, "secondary model"):
        secondary_model = SecondaryDiffusionImageNet2()
        secondary_model.load_state_dict(torch.load(f'{model_path}/secondary_model_imagenet_2.pth', map_location='cpu'))
        secondary_model.eval().requires_grad_(False).to(device)
    return secondary_model

def load_lpips_model(net: str = 'vgg'):
    with track_model_vram(device, "LPIPS model"):
        lpips_model = lpips.LPIPS(net=net, verbose=False).to(device)
    return lpips_model


# Map model parameter names to the load names
model_load_name_map = {
    'ViTB32': 'ViT-B/32',
    'ViTB16': 'ViT-B/16',
    'ViTL14': 'ViT-L/14',
    'ViTL14_336': 'ViT-L/14@336px',
    'RN50': 'RN50',
    'RN50x4': 'RN50x4',
    'RN50x16': 'RN50x16',
    'RN50x64': 'RN50x64',
    'RN101': 'RN101',
    'ViTB32_laion2b_e16': 'ViTB32_laion2b_e16',
    'ViTB32_laion400m_e31': 'ViTB32_laion400m_e31',
    'ViTB32_laion400m_32': 'ViTB32_laion400m_32',
    'ViTB32quickgelu_laion400m_e31': 'ViTB32quickgelu_laion400m_e31',
    'ViTB32quickgelu_laion400m_e32': 'ViTB32quickgelu_laion400m_e32',
    'ViTB16_laion400m_e31': 'ViTB16_laion400m_e31',
    'ViTB16_laion400m_e32': 'ViTB16_laion400m_e32',
    'RN50_yffcc15m': 'RN50_yffcc15m',
    'RN50_cc12m': 'RN50_cc12m',
    'RN50_quickgelu_yfcc15m': 'RN50_quickgelu_yfcc15m',
    'RN50_quickgelu_cc12m': 'RN50_quickgelu_cc12m',
    'RN101_yfcc15m': 'RN101_yfcc15m',
    'RN101_quickgelu_yfcc15m': 'RN101_quickgelu_yfcc15m'
}


clip_managers = [
    ClipManager(
        name=model_name,
        cut_count_multiplier=eval(model_name),
        download_root=model_path_clip,
        device=device,
        use_cut_heatmap=cut_heatmaps,
        pad_inner_cuts=True
    )
    for model_name in CLIP_NAME_MAP.keys() if eval(model_name)
]

clip_modelname = [model_name for model_name in model_load_name_map.keys() if eval(model_name) > 0.0]
clip_model_weights = [eval(model_name) for model_name in model_load_name_map.keys() if eval(model_name) > 0.0]

# Get corrected sizes
side_x = (width_height[0] // 64) * 64
side_y = (width_height[1] // 64) * 64
if side_x != width_height[0] or side_y != width_height[1]:
    print(f'Changing output size to {side_x}x{side_y}. Dimensions must by multiples of 64.')

estimate_vram_requirements(
    side_x=side_x,
    side_y=side_y,
    cut_innercut=cut_innercut,
    cut_overview=cut_overview,
    clip_model_names=clip_modelname,
    diffusion_model_name=diffusion_model.name,
    use_secondary=use_secondary_model,
    device=device
)
lpips_model = load_lpips_model()
if use_secondary_model:
    secondary_model = load_secondary_model()

print('\nLoading CLIP Models:\n')
# Load the CLIP models
for clip_manager in clip_managers:
    clip_manager.load()

# Update Model Settings
timestep_respacing = f'ddim{steps}'
diffusion_steps = (1000 // steps) * steps if steps < 1000 else steps
model_config.update({
    'timestep_respacing': timestep_respacing,
    'diffusion_steps': diffusion_steps,
})

# Make folder for batch
batchFolder = f'{outDirPath}/{batch_name}'
createPath(batchFolder)
"""###Animation Settings"""

# @markdown ####**Animation Mode:**
animation_mode = "None"  # @param['None', '2D', 'Video Input']
# @markdown *For animation, you probably want to turn `cutn_batches` to 1 to make it quicker.*

# @markdown ---

# @markdown ####**Video Input Settings:**
# video_init_path = "/content/training.mp4" #@param {type: 'string'}
# extract_nth_frame = 2 #@param {type:"number"}

if animation_mode == "Video Input":
    videoFramesFolder = f'/content/videoFrames'
    createPath(videoFramesFolder)
    print(f"Exporting Video Frames (1 every {extract_nth_frame})...")
    try:
        #!rm {videoFramesFolder}/*.jpg
        tempfileList = glob.glob(videoFramesFolder + '/*.jpg')
        for tempfilePath in tempfileList:
            os.remove(tempfilePath)
    except:
        print('')
    vf = f'"select=not(mod(n\,{extract_nth_frame}))"'
    subprocess.run([
        'ffmpeg', '-i', f'{video_init_path}', '-vf', f'{vf}', '-vsync', 'vfr',
        '-q:v', '2', '-loglevel', 'error', '-stats',
        f'{videoFramesFolder}/%04d.jpg'
    ],
        stdout=subprocess.PIPE).stdout.decode('utf-8')


if animation_mode == "Video Input":
    max_frames = len(glob(f'{videoFramesFolder}/*.jpg'))


def parse_key_frames(string, prompt_parser=None):
    """Given a string representing frame numbers paired with parameter values at that frame,
    return a dictionary with the frame numbers as keys and the parameter values as the values.

    Parameters
    ----------
    string: string
        Frame numbers paired with parameter values at that frame number, in the format
        'framenumber1: (parametervalues1), framenumber2: (parametervalues2), ...'
    prompt_parser: function or None, optional
        If provided, prompt_parser will be applied to each string of parameter values.

    Returns
    -------
    dict
        Frame numbers as keys, parameter values at that frame number as values

    Raises
    ------
    RuntimeError
        If the input string does not match the expected format.

    Examples
    --------
    >>> parse_key_frames("10:(Apple: 1| Orange: 0), 20: (Apple: 0| Orange: 1| Peach: 1)")
    {10: 'Apple: 1| Orange: 0', 20: 'Apple: 0| Orange: 1| Peach: 1'}

    >>> parse_key_frames("10:(Apple: 1| Orange: 0), 20: (Apple: 0| Orange: 1| Peach: 1)", prompt_parser=lambda x: x.lower()))
    {10: 'apple: 1| orange: 0', 20: 'apple: 0| orange: 1| peach: 1'}
    """
    pattern = r'((?P<frame>[0-9]+):[\s]*[\(](?P<param>[\S\s]*?)[\)])'
    frames = dict()
    for match_object in re.finditer(pattern, string):
        frame = int(match_object.groupdict()['frame'])
        param = match_object.groupdict()['param']
        if prompt_parser:
            frames[frame] = prompt_parser(param)
        else:
            frames[frame] = param

    if frames == {} and len(string) != 0:
        raise RuntimeError('Key Frame string not correctly formatted')
    return frames


def get_inbetweens(key_frames, integer=False):
    """Given a dict with frame numbers as keys and a parameter value as values,
    return a pandas Series containing the value of the parameter at every frame from 0 to max_frames.
    Any values not provided in the input dict are calculated by linear interpolation between
    the values of the previous and next provided frames. If there is no previous provided frame, then
    the value is equal to the value of the next provided frame, or if there is no next provided frame,
    then the value is equal to the value of the previous provided frame. If no frames are provided,
    all frame values are NaN.

    Parameters
    ----------
    key_frames: dict
        A dict with integer frame numbers as keys and numerical values of a particular parameter as values.
    integer: Bool, optional
        If True, the values of the output series are converted to integers.
        Otherwise, the values are floats.

    Returns
    -------
    pd.Series
        A Series with length max_frames representing the parameter values for each frame.

    Examples
    --------
    >>> max_frames = 5
    >>> get_inbetweens({1: 5, 3: 6})
    0    5.0
    1    5.0
    2    5.5
    3    6.0
    4    6.0
    dtype: float64

    >>> get_inbetweens({1: 5, 3: 6}, integer=True)
    0    5
    1    5
    2    5
    3    6
    4    6
    dtype: int64
    """
    key_frame_series = pd.Series([np.nan for a in range(max_frames)])

    for i, value in key_frames.items():
        key_frame_series[i] = value
    key_frame_series = key_frame_series.astype(float)

    interp_method = interp_spline

    if interp_method == 'Cubic' and len(key_frames.items()) <= 3:
        interp_method = 'Quadratic'

    if interp_method == 'Quadratic' and len(key_frames.items()) <= 2:
        interp_method = 'Linear'

    key_frame_series[0] = key_frame_series[key_frame_series.first_valid_index()]
    key_frame_series[max_frames - 1] = key_frame_series[key_frame_series.last_valid_index()]
    # key_frame_series = key_frame_series.interpolate(method=intrp_method,order=1, limit_direction='both')
    key_frame_series = key_frame_series.interpolate(method=interp_method.lower(), limit_direction='both')
    if integer:
        return key_frame_series.astype(int)
    return key_frame_series


def split_prompts(prompts):
    # Take the discrete prompts provided and build a frame-by-frame list of prompts that will be used
    # Fill any gaps between frame numbers with the previous prompt.
    # (Why do we use a dict with serial integer indices instead of a list??)
    prompt_series = {}
    i = 0
    last_k = -1
    last_prompt = []
    for k, v in prompts.items():
        if int(k) > last_k:
            while last_k < int(k):
                last_k += 1
                prompt_series.update({last_k: last_prompt})
        prompt_series.update({int(k): v})
        last_k = int(k)
        if type(v) != type(last_prompt):
            del last_prompt
        last_prompt = v
    # now fill the list until we get to max_frames, for future animation support
    if last_k < max_frames:
        while last_k < max_frames:
            last_k += 1
            prompt_series.update({last_k: last_prompt})
    return prompt_series


if key_frames:
    try:
        angle_series = get_inbetweens(parse_key_frames(angle))
    except RuntimeError as e:
        print(
            "WARNING: You have selected to use key frames, but you have not "
            "formatted `angle` correctly for key frames.\n"
            "Attempting to interpret `angle` as "
            f'"0: ({angle})"\n'
            "Please read the instructions to find out how to use key frames "
            "correctly.\n"
        )
        angle = f"0: ({angle})"
        angle_series = get_inbetweens(parse_key_frames(angle))

    try:
        zoom_series = get_inbetweens(parse_key_frames(zoom))
    except RuntimeError as e:
        print(
            "WARNING: You have selected to use key frames, but you have not "
            "formatted `zoom` correctly for key frames.\n"
            "Attempting to interpret `zoom` as "
            f'"0: ({zoom})"\n'
            "Please read the instructions to find out how to use key frames "
            "correctly.\n"
        )
        zoom = f"0: ({zoom})"
        zoom_series = get_inbetweens(parse_key_frames(zoom))

    try:
        translation_x_series = get_inbetweens(parse_key_frames(translation_x))
    except RuntimeError as e:
        print(
            "WARNING: You have selected to use key frames, but you have not "
            "formatted `translation_x` correctly for key frames.\n"
            "Attempting to interpret `translation_x` as "
            f'"0: ({translation_x})"\n'
            "Please read the instructions to find out how to use key frames "
            "correctly.\n"
        )
        translation_x = f"0: ({translation_x})"
        translation_x_series = get_inbetweens(parse_key_frames(translation_x))

    try:
        translation_y_series = get_inbetweens(parse_key_frames(translation_y))
    except RuntimeError as e:
        print(
            "WARNING: You have selected to use key frames, but you have not "
            "formatted `translation_y` correctly for key frames.\n"
            "Attempting to interpret `translation_y` as "
            f'"0: ({translation_y})"\n'
            "Please read the instructions to find out how to use key frames "
            "correctly.\n"
        )
        translation_y = f"0: ({translation_y})"
        translation_y_series = get_inbetweens(parse_key_frames(translation_y))

else:
    angle = float(angle)
    zoom = float(zoom)
    translation_x = float(translation_x)
    translation_y = float(translation_y)

intermediates_in_subfolder = True

# Save a checkpoint at 20% for use as a later init image
if geninit:
    intermediate_saves = [int(steps * geninitamount)]
    print(f'debug: steps is {steps} and geninitamount is {geninitamount}')
    print(f'debug: intermediate_saves is {intermediate_saves}')

# processes a setting that can be done at certain steps
# which includes a number of steps based on overall steps, in which case we turn that into a list of specific steps
# or if a list it can be a list of specific steps,
# or a list of floats (multiple of overall steps) which we convert to specific steps
# that way later we only have to deal with a list of specific steps. Crazy, right?
def do_at_step(value, steps, skip_steps):
    new_value = []
    if type(value) is list:
        for val in value:
            if type(val) is float:
                val = int(steps * val)
            new_value.append(val)
    elif value == 0:
        new_value = [0]
    else:
        interval = math.floor((steps - skip_steps - 1) // (value + 1))
        this_step = interval
        while this_step <= steps:
            new_value.append(this_step)
            this_step += interval
    return new_value

intermediate_saves = do_at_step(intermediate_saves, steps, skip_steps)

if simple_symmetry != [0]:
    simple_symmetry = do_at_step(simple_symmetry, steps, skip_steps)
    print(f'Simple symmetry will happen at {simple_symmetry} steps')

if intermediate_saves and intermediates_in_subfolder is True:
    partialFolder = f'{batchFolder}/partials'
    createPath(partialFolder)

batch_size = 1


def move_files(start_num, end_num, old_folder, new_folder):
    for i in range(start_num, end_num):
        old_file = old_folder + f'/{batch_name}({batchNum})_{i:04}.png'
        new_file = new_folder + f'/{batch_name}({batchNum})_{i:04}.png'
        os.rename(old_file, new_file)


resume_run = False  # @param{type: 'boolean'}
run_to_resume = 'latest'  # @param{type: 'string'}
resume_from_frame = 'latest'  # @param{type: 'string'}
retain_overwritten_frames = False  # @param{type: 'boolean'}
if retain_overwritten_frames is True:
    retainFolder = f'{batchFolder}/retained'
    createPath(retainFolder)

skip_step_ratio = int(frames_skip_steps.rstrip("%")) / 100
calc_frames_skip_steps = math.floor(steps * skip_step_ratio)

if steps <= calc_frames_skip_steps:
    sys.exit("ERROR: You can't skip more steps than your total steps")

if resume_run:
    if run_to_resume == 'latest':
        try:
            batchNum
        except:
            batchNum = len(glob(f"{batchFolder}/{batch_name}(*)_settings.json")) - 1
    else:
        batchNum = int(run_to_resume)
    if resume_from_frame == 'latest':
        start_frame = len(glob(batchFolder + f"/{batch_name}({batchNum})_*.png"))
    else:
        start_frame = int(resume_from_frame) + 1
        if retain_overwritten_frames is True:
            existing_frames = len(glob(batchFolder + f"/{batch_name}({batchNum})_*.png"))
            frames_to_save = existing_frames - start_frame
            print(f'Moving {frames_to_save} frames to the Retained folder')
            move_files(start_frame, existing_frames, batchFolder, retainFolder)
else:
    if "_" in batch_name:
        print(f'Replacing _ with - in batch_name to keep file numbering logic from exploding.')
        batch_name = batch_name.replace('_', '-')
    start_frame = 0
    #batchNum = len(glob(batchFolder + "/*.json"))
    # changing old naming method -- intstead of counting files, take the highest numbered file + 1
    files = os.listdir(batchFolder)
    count = 0
    filenums = []
    for file in files:
        if batch_name in file and ".json" in file:
            start = file.index('_')
            end = file.index('_', start+1)
            filenum = int(file[(start + 1):end])
            filenums.append(filenum)
    if not filenums:
        batchNum = 0
    else:
        batchNum = max(filenums) + 1

print(f'\nStarting Run: {batch_name}({batchNum}) at frame {start_frame}')

if set_seed == 'random_seed':
    random.seed()
    seed = random.randint(0, 2**32)
    # print(f'Using seed: {seed}')
else:
    seed = int(set_seed)

# convert old number-style settings to new scheduled settings
og_cut_ic_pow = cut_ic_pow
if type(cut_ic_pow) != str:
    if type(cut_ic_pow_final) != type(None):
        cut_ic_pow = num_to_schedule(cut_ic_pow, cut_ic_pow_final)
    else:
        cut_ic_pow = num_to_schedule(cut_ic_pow)

if type(clip_guidance_scale) != str:
    clip_guidance_scale = num_to_schedule(clip_guidance_scale)

print(f'Using seed {seed}')


# Leave this section alone, it takes all our settings and puts them in one variable dictionary
args = {
    'batchNum': batchNum,
    'prompts_series': split_prompts(text_prompts) if text_prompts else None,
    'image_prompts_series':
    split_prompts(image_prompts) if image_prompts else None,
    'seed': seed,
    'display_rate': display_rate,
    'n_batches': n_batches if animation_mode == 'None' else 1,
    'batch_size': batch_size,
    'batch_name': batch_name,
    'steps': steps,
    'sampling_mode': sampling_mode,
    'width_height': width_height,
    'clip_guidance_scale': eval(clip_guidance_scale),
    'tv_scale': tv_scale,
    'range_scale': range_scale,
    'sat_scale': sat_scale,
    'cutn_batches': eval(cutn_batches),
    'init_image': init_image,
    'init_scale': init_scale,
    'skip_steps': skip_steps,
    'sharpen_preset': sharpen_preset,
    'keep_unsharp': keep_unsharp,
    'side_x': side_x,
    'side_y': side_y,
    'timestep_respacing': timestep_respacing,
    'diffusion_steps': diffusion_steps,
    'animation_mode': animation_mode,
    'video_init_path': video_init_path,
    'extract_nth_frame': extract_nth_frame,
    'key_frames': key_frames,
    'max_frames': max_frames if animation_mode != "None" else 1,
    'interp_spline': interp_spline,
    'start_frame': start_frame,
    'angle': angle,
    'zoom': zoom,
    'translation_x': translation_x,
    'translation_y': translation_y,
    'angle_series': angle_series,
    'zoom_series': zoom_series,
    'translation_x_series': translation_x_series,
    'translation_y_series': translation_y_series,
    'frames_scale': frames_scale,
    'calc_frames_skip_steps': calc_frames_skip_steps,
    'skip_step_ratio': skip_step_ratio,
    'calc_frames_skip_steps': calc_frames_skip_steps,
    'text_prompts': text_prompts,
    'image_prompts': image_prompts,
    'cut_overview': eval(cut_overview),
    'cut_innercut': eval(cut_innercut),
    'cut_ic_pow': eval(cut_ic_pow),
    'cut_ic_pow_final': cut_ic_pow_final,
    'cut_icgray_p': eval(cut_icgray_p),
    'intermediate_saves': intermediate_saves,
    'intermediates_in_subfolder': intermediates_in_subfolder,
    'perlin_init': perlin_init,
    'perlin_mode': perlin_mode,
    'set_seed': set_seed,
    'eta': eta,
    'clamp_grad': clamp_grad,
    'clamp_max': eval(clamp_max),
    'skip_augs': skip_augs,
    'randomize_class': randomize_class,
    'clip_denoised': clip_denoised,
    'fuzzy_prompt': fuzzy_prompt,
    'rand_mag': rand_mag,
    'stop_early': stop_early,
    'symmetry_loss_v': symmetry_loss_v,
    'symmetry_loss_h': symmetry_loss_h,
    'symm_loss_scale': eval(symm_loss_scale),
    'symm_switch': symm_switch,
    'simple_symmetry': simple_symmetry,
    'smooth_schedules': smooth_schedules,
    'render_mask': render_mask,
    'perlin_brightness': perlin_brightness,
    'perlin_contrast': perlin_contrast,
    'cool_down': cool_down
}

args = SimpleNamespace(**args)

# Smooth out them tasty schedules if the user wills it so...
if smooth_schedules == True:
    args.cutn_batches = smooth_jazz(args.cutn_batches)
    args.cut_overview = smooth_jazz(args.cut_overview)
    args.cut_innercut = smooth_jazz(args.cut_innercut)
    args.cut_ic_pow = smooth_jazz(args.cut_ic_pow)
    args.clip_guidance_scale = smooth_jazz(args.clip_guidance_scale)
    args.clamp_max = smooth_jazz(args.clamp_max)
    args.symm_loss_scale = smooth_jazz(args.symm_loss_scale)

if cl_args.gobiginit == None:
    model, diffusion = create_model_and_diffusion(**model_config)
    model.load_state_dict(torch.load(f'{model_path}/{diffusion_model.path}', map_location='cpu'))
    model.requires_grad_(False).eval()
    for name, param in model.named_parameters():
        if 'qkv' in name or 'norm' in name or 'proj' in name:
            param.requires_grad_()
    if model_config['use_fp16']:
        model.convert_to_fp16()
    model.to(device)
    gc.collect()
    if "cuda" in str(device):
        with torch.cuda.device(device):
            torch.cuda.empty_cache()

# FUNCTIONS FOR GO BIG MODE
slices_todo = 0  # several things use this, so defining it out here

def addalpha(im, mask):
    imr, img, imb, ima = im.split()
    mmr, mmg, mmb, mma = mask.split()
    im = Image.merge('RGBA', [imr, img, imb, mma])  # we want the RGB from the original, but the transparency from the mask
    return(im)

# Alternative method composites a grid of images at the positions provided
def grid_merge(source, slices):
    source.convert("RGBA")
    for slice, posx, posy in slices: # go in reverse to get proper stacking
        source.alpha_composite(slice, (posx, posy))
    return source

def grid_coords(target, original, overlap):
    #generate a list of coordinate tuples for our sections, in order of how they'll be rendered
    #target should be the size for the gobig result, original is the size of each chunk being rendered
    center = []
    target_x, target_y = target
    center_x = int(target_x / 2)
    center_y = int(target_y / 2)
    original_x, original_y = original
    x = center_x - int(original_x / 2)
    y = center_y - int(original_y / 2)
    center.append((x,y)) #center chunk
    uy = y #up
    uy_list = []
    dy = y #down
    dy_list = []
    lx = x #left
    lx_list = []
    rx = x #right
    rx_list = []
    while uy > 0: #center row vertical up
        uy = uy - original_y + overlap
        uy_list.append((lx, uy))
    while (dy + original_y) <= target_y: #center row vertical down
        dy = dy + original_y - overlap
        dy_list.append((rx, dy))
    while lx > 0:
        lx = lx - original_x + overlap
        lx_list.append((lx, y))
        uy = y
        while uy > 0:
            uy = uy - original_y + overlap
            uy_list.append((lx, uy))
        dy = y
        while (dy + original_y) <= target_y:
            dy = dy + original_y - overlap
            dy_list.append((lx, dy))
    while (rx + original_x) <= target_x:
        rx = rx + original_x - overlap
        rx_list.append((rx, y))
        uy = y
        while uy > 0:
            uy = uy - original_y + overlap
            uy_list.append((rx, uy))
        dy = y
        while (dy + original_y) <= target_y:
            dy = dy + original_y - overlap
            dy_list.append((rx, dy))
    # calculate a new size that will fill the canvas, which will be optionally used in grid_slice and go_big
    last_coordx, last_coordy = dy_list[-1:][0]
    render_edgey = last_coordy + original_y # outer bottom edge of the render canvas
    render_edgex = last_coordx + original_x # outer side edge of the render canvas
    scalarx = render_edgex / target_x
    scalary = render_edgey / target_y
    if scalarx <= scalary:
        new_edgex = int(target_x * scalarx)
        new_edgey = int(target_y * scalarx)
    else:
        new_edgex = int(target_x * scalary)
        new_edgey = int(target_y * scalary)
    # now put all the chunks into one master list of coordinates (essentially reverse of how we calculated them so that the central slices will be on top)
    result = []
    for coords in dy_list[::-1]:
        result.append(coords)
    for coords in uy_list[::-1]:
        result.append(coords)
    for coords in rx_list[::-1]:
        result.append(coords)
    for coords in lx_list[::-1]:
        result.append(coords)
    result.append(center[0])
    return result, (new_edgex, new_edgey)

# Chop our source into a grid of images that each equal the size of the original render
def grid_slice(source, overlap, og_size, maximize=False): 
    width, height = og_size # size of the slices to be rendered
    coordinates, new_size = grid_coords(source.size, og_size, overlap)
    if maximize == True:
        source = source.resize(new_size, get_resampling_mode()) # minor concern that we're resizing twice
        coordinates, new_size = grid_coords(source.size, og_size, overlap) # re-do the coordinates with the new canvas size
    # loc_width and loc_height are the center point of the goal size, and we'll start there and work our way out
    slices = []
    for coordinate in coordinates:
        x, y = coordinate
        slices.append(((source.crop((x, y, x+width, y+height))), x, y))
    global slices_todo
    slices_todo = len(slices) - 1
    return slices, new_size

# FINALLY DO THE RUN
try:
    if (cl_args.gui):
        print("Using the gui this way is deprecated. Invoke it first with 'python prdgui.py'")
    print(f'\nStarting batch!')
    for batch_image in range(n_batches):
        og_size = (side_x, side_y)
        if cl_args.gobiginit is None:
            do_run(batch_image)
        if letsgobig:
            # Clear out the heatmaps from the original image, since the size is going to change
            for clip_manager in clip_managers:
                clip_manager.cut_heatmap = None

            if cl_args.gobig_slices:
                slices_todo = cl_args.gobig_slices
            else:
                slices_todo = (gobig_scale * gobig_scale) + 1  # we want 5 total slices for a 2x increase, 4 to match the total pixel increase + 1 to cover overlap
            temp_args = SimpleNamespace(**vars(args))  # make a backup copy of args so we can reset it after gobig
            if cl_args.cuda != '0':
                progress_image = (f'progress{cl_args.cuda}.png')
            else:
                progress_image = 'progress.png'
            # grab the init image and make it our progress image
            if cl_args.gobiginit is not None:
                shutil.copy(init_image, progress_image)                
            # Setup some filenames
            if cl_args.cuda != '0':  # handle if a different GPU is in use
                slice_image = (f'slice{cl_args.cuda}.png')
                slice_imask = (f'slice_imask{cl_args.cuda}.png')
                slice_rmask = (f'slice_rmask{cl_args.cuda}.png')
                final_output_image = (f'{batchFolder}/{batch_name}_go_big_{cl_args.cuda}_{batchNum}_{batch_image}.png')
            else:
                slice_image = 'slice.png'
                slice_imask = 'slice_imask.png'
                slice_rmask = 'slice_rmask.png'
                final_output_image = (f'{batchFolder}/{batch_name}_go_big_{batchNum}_{batch_image}.png')

            # To keep things simple (hah), we'll create a fully white render_mask to use in the case that there's no provided render_mask
            # that way there's going to be a render_mask no matter what, and we don't have to keep checking for it
            # And just to keep everyone on their toes, a render_mask is is for telling do_run where to render/not render, while a mask is for gobig to blend slices, and an init_mask is what to render against when rendering with an rmask -- got it?
            # Resize init if needed, as well as any render mask. For now we assume the render mask matches the size of the init.
            if cl_args.gobiginit_scaled == False:
                input_image = Image.open(progress_image).convert('RGBA')
                reside_x = side_x * gobig_scale
                reside_y = side_y * gobig_scale
                source_image = input_image.resize((reside_x, reside_y), get_resampling_mode())
                input_image.close()
            else:
                source_image = Image.open(progress_image).convert('RGBA')
                og_size = (int(side_x / gobig_scale), int(side_y / gobig_scale)) # we want to render sections that are what the original pre-scaled size probably was
            # Slice source_image into overlapping slices
            slices, new_canvas_size = grid_slice(source_image, gobig_overlap, og_size, gobig_maximize)
            # Gobig_maximize increases our render canvas to include otherwise wasted pixels.
            if gobig_maximize == True: #TODO: optimize this so we don't have to run the slicer again
                source_image = source_image.resize(new_canvas_size, get_resampling_mode())
                slices, new_canvas_size = grid_slice(source_image, gobig_overlap, og_size) # now that we have the ultimate size, we have to get a new set of coords
                print(f'GOBIG maximize is on. New size is now {source_image.size}')
            if render_mask is not None:
                source_render_mask = Image.open(render_mask).convert('RGBA')
                source_render_mask = source_render_mask.resize(source_image.size, get_resampling_mode())
                rmasks = grid_slice(source_render_mask, gobig_overlap, og_size)
            else:
                rmasks = None
            if init_masked is not None:
                source_imask = Image.open(init_masked).convert('RGBA')
                source_imask = source_imask.resize(source_image.size, get_resampling_mode())
                imasks = grid_slice(source_imask, gobig_overlap, og_size)
            else:
                imasks = None

            # Run PRD again for each slice, with proper init image paramaters, etc.
            betterslices = []
            #for chunk, chunk_rmask, chunk_imask in slices:
            for count, chunk_w_coords in enumerate(slices):
                chunk, coord_x, coord_y = chunk_w_coords
                if rmasks is not None:
                    chunk_rmask = rmasks[count][0]
                else:
                    chunk_rmask = None
                if imasks is not None:
                    chunk_imask = imasks[count][0]
                else:
                    chunk_imask = None
                seed = seed + 1
                args.seed = seed
                # Reset underlying systems for another run
                model, diffusion = create_model_and_diffusion(**model_config)
                model.load_state_dict(torch.load(f'{model_path}/{diffusion_model.path}', map_location='cpu'))
                model.requires_grad_(False).eval().to(device)
                for name, param in model.named_parameters():
                    if 'qkv' in name or 'norm' in name or 'proj' in name:
                        param.requires_grad_()
                if model_config['use_fp16']:
                    model.convert_to_fp16()
                gc.collect()
                if "cuda" in str(device):
                    with torch.cuda.device(device):
                        torch.cuda.empty_cache()
                # Some original values need to be adjusted for go_big to work properly
                chunk.save(slice_image)
                if chunk_rmask is not None:
                    chunk_rmask.save(slice_rmask)
                if chunk_imask is not None:
                    chunk_imask.save(slice_imask)
                args.init_image = slice_image
                init_image = slice_image
                if chunk_rmask is not None:
                    args.render_mask = slice_rmask
                    render_mask = slice_rmask
                if chunk_imask is not None:
                    init_masked = slice_imask
                    args.init_masked = slice_imask
                args.symmetry_loss_v = False
                args.symmetry_loss_h = False
                args.perlin_init = False
                perlin_init = False
                args.skip_steps = int(steps * gobig_skip_ratio)
                args.side_x, args.side_y = chunk.size
                side_x, side_y = chunk.size
                args.fix_brightness_contrast = False
                args.symm_loss_h = False
                args.symm_loss_v = False
                args.simple_symmetry = [0]
                do_run(batch_image, count)
                print(f'Finished slice, grabbing {progress_image} and adding it to betterslices.')
                resultslice = Image.open(progress_image).convert('RGBA')
                betterslices.append((resultslice.copy(), coord_x, coord_y)) #TODO add coordinates here
                resultslice.close()
            #TODO replace below with new alpha masks and place them appropriately
            # generate an alpha mask for compositing the chunks
            alpha = Image.new('L', (args.side_x, args.side_y), color=0xFF)
            alpha_gradient = ImageDraw.Draw(alpha)
            a = 0
            i = 0
            overlap = gobig_overlap
            shape = ((args.side_x, args.side_y), (0,0))
            while i < overlap:
                alpha_gradient.rectangle(shape, fill = a)
                a += 4
                i += 1
                shape = ((args.side_x - i, args.side_y - i), (i,i))
            mask = Image.new('RGBA', (args.side_x, args.side_y), color=0)
            mask.putalpha(alpha)
            finished_slices = []
            for betterslice, x, y in betterslices:
                finished_slice = addalpha(betterslice, mask)
                finished_slices.append((finished_slice, x, y))
            # # Once we have all our images, use grid_merge back onto the source, then save
            final_output = grid_merge(source_image, finished_slices)
            final_output.save(final_output_image)
            print(f'\n\nGO BIG is complete!\n\n ***** NOTE *****\nYour output is saved as {final_output_image}!')
            # set everything back for the next image in the batch
            args = temp_args            
        gc.collect()
        if "cuda" in str(device):
            with torch.cuda.device(device):
                torch.cuda.empty_cache()

except KeyboardInterrupt:
    pass
finally:
    print('\n\nAll image(s) finished.')
    log_max_allocated(device)
    gc.collect()
    if "cuda" in str(device):
        with torch.cuda.device(device):
            torch.cuda.empty_cache()

# @title ### **Create video**

skip_video_for_run_all = True  # @param {type: 'boolean'}

if skip_video_for_run_all == False:
    # import subprocess in case this cell is run without the above cells
    import subprocess
    from base64 import b64encode

    latest_run = batchNum

    folder = batch_name  # @param
    run = latest_run  # @param
    final_frame = 'final_frame'

    init_frame = 1  # @param {type:"number"} This is the frame where the video will start
    last_frame = final_frame  # @param {type:"number"} You can change i to the number of the last frame you want to generate. It will raise an error if that number of frames does not exist.
    fps = 12  # @param {type:"number"}
    view_video_in_cell = False  # @param {type: 'boolean'}

    frames = []

    if last_frame == 'final_frame':
        last_frame = len(glob(batchFolder + f"/{folder}({run})_*.png"))
        print(f'Total frames: {last_frame}')

    image_path = f"{outDirPath}/{folder}/{folder}({run})_%04d.png"
    filepath = f"{outDirPath}/{folder}/{folder}({run}).mp4"

    cmd = [
        'ffmpeg', '-y', '-vcodec', 'png', '-r',
        str(fps), '-start_number',
        str(init_frame), '-i', image_path, '-frames:v',
        str(last_frame + 1), '-c:v', 'libx264', '-vf', f'fps={fps}',
        '-pix_fmt', 'yuv420p', '-crf', '17', '-preset', 'very ', filepath
    ]

    process = subprocess.Popen(
        cmd,
        cwd=f'{batchFolder}',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(stderr)
        raise RuntimeError(stderr)
    else:
        print("The video is ready")
