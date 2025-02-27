import math
import cv2
import time
import requests
import random
import numpy as np
import onnxruntime as ort
from PIL import Image
from pathlib import Path
from collections import OrderedDict,namedtuple


# set cuda = true if you have an NVIDIA GPU
cuda = True

w = "./ONNX_models/20230420_12class_960_1.onnx"
img = cv2.imread('./Columbus_COWC_1.png')

names = ['car', 'van', 'truck', 'building', 'human', 'gastank', 'digger', 'container', 'bus', 'pylon', 'boat', 'bike']
colors = {name:[random.randint(0, 255) for _ in range(3)] for i,name in enumerate(names)}


providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if cuda else ['CPUExecutionProvider']
session = ort.InferenceSession(w, providers=providers)



def letterbox(im, new_shape=(960, 960), color=(114, 114, 114), auto=True, scaleup=True, stride=32):
    # Resize and pad image while meeting stride-multiple constraints
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:  # only scale down, do not scale up (for better val mAP)
        r = min(r, 1.0)

    # Compute padding
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding

    if auto:  # minimum rectangle
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)  # wh padding

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)  # add border
    return im, r, (dw, dh)

def split_image(image, tile_size=(960, 960), padding=(0, 0)):
    height, width, _ = image.shape
    tile_height, tile_width = tile_size
    pad_height, pad_width = padding

    # Calculate the number of tiles needed in each dimension
    num_tiles_x = math.ceil(width / tile_width)
    num_tiles_y = math.ceil(height / tile_height)

    # Pad the image to ensure it's divisible by the tile size
    padded_image = cv2.copyMakeBorder(
        image,
        0,
        tile_height * num_tiles_y - height + pad_height * 2,
        0,
        tile_width * num_tiles_x - width + pad_width * 2,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )

    # Split the image into tiles
    tiles = []
    for y in range(num_tiles_y):
        for x in range(num_tiles_x):
            tile = padded_image[
                y * tile_height : (y + 1) * tile_height + pad_height * 2,
                x * tile_width : (x + 1) * tile_width + pad_width * 2,
                :,
            ]
            tiles.append(((x, y), tile))

    return tiles, padded_image.shape[:2]

def merge_tiles(tiles, output_shape, padding=(0, 0)):
    tile_height, tile_width = tiles[0][1].shape[:2]
    num_tiles_x = output_shape[1] // (tile_width - 2 * padding[1])
    num_tiles_y = output_shape[0] // (tile_height - 2 * padding[0])

    merged_image = np.zeros((*output_shape, 3), dtype=np.uint8)

    for (x, y), tile in tiles:
        tile_no_padding = tile[padding[0] : -padding[0], padding[1] : -padding[1], :]
        merged_image[
            y * (tile_height - 2 * padding[0]) : (y + 1) * (tile_height - 2 * padding[0]),
            x * (tile_width - 2 * padding[1]) : (x + 1) * (tile_width - 2 * padding[1]),
            :,
        ] = tile_no_padding

    return merged_image


# Load the image and split it into tiles
tile_size = (960, 960)
padding = (32, 32)
tiles, padded_shape = split_image(img, tile_size=tile_size, padding=padding)
# Initialize a dictionary to store the count of each category
category_count = {name: 0 for name in names}

# Process each tile with the ONNX model
processed_tiles = []
for i, (tile_idx, tile) in enumerate(tiles):
    image = tile.copy()
    image, ratio, dwdh = letterbox(image, new_shape=tile_size, auto=False)
    image = image.transpose((2, 0, 1))
    image = np.expand_dims(image, 0)
    image = np.ascontiguousarray(image)

    im = image.astype(np.float32)
    im /= 255

    inp = {inname[0]: im}
    outputs = session.run(outname, inp)[0]

    for i, (batch_id, x0, y0, x1, y1, cls_id, score) in enumerate(outputs):
        box = np.array([x0, y0, x1, y1])
        box -= np.array(dwdh * 2)
        box /= ratio
        box = box.round().astype(np.int32).tolist()
        cls_id = int(cls_id)
        score = round(float(score), 3)
        name = names[cls_id]
        color = colors[name]
        name += ' ' + str(score)
        cv2.rectangle(tile, box[:2], box[2:], color, 2)
        cv2.putText(tile, name, (box[0], box[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.75, [225, 255, 255], thickness=2)

        # Update the count for the detected category
        category_count[name.split()[0]] += 1

    processed_tiles.append((tile_idx, tile))

# Merge the processed tiles back into the original image
merged_image = merge_tiles(processed_tiles, padded_shape, padding=padding)

# Remove padding from the merged image to get the final output
final_image = merged_image[: img.shape[0], : img.shape[1], :]
    
# Convert color space from RGB to BGR
final_image_bgr = cv2.cvtColor(final_image, cv2.COLOR_RGB2BGR)

# Save the final image
cv2.imwrite('./Columbus_out.jpg', final_image)


# Print the total count of each class
print("Total count of each class:")
for name, count in category_count.items():
    print(f"{name}: {count}")