from pycocotools.coco import COCO
import tensorflow as tf
import numpy as np
import imageio
from skimage.color import gray2rgb
from random import sample, shuffle
import os

from inference import numpy_bbox_to_image
from data.augmentation import detr_aug
from data import processing
import matplotlib.pyplot as plt


CLASS_NAME = [
    'N/A', 'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus',
    'train', 'truck', 'boat', 'traffic light', 'fire hydrant', 'N/A',
    'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse',
    'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'N/A', 'backpack',
    'umbrella', 'N/A', 'N/A', 'handbag', 'tie', 'suitcase', 'frisbee', 'skis',
    'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove',
    'skateboard', 'surfboard', 'tennis racket', 'bottle', 'N/A', 'wine glass',
    'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich',
    'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake',
    'chair', 'couch', 'potted plant', 'bed', 'N/A', 'dining table', 'N/A',
    'N/A', 'toilet', 'N/A', 'tv', 'laptop', 'mouse', 'remote', 'keyboard',
    'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'N/A',
    'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier',
    'toothbrush', "back"
]


def get_coco_labels(coco, img_id, image_shape, augmentation):
    # Load the labels the instances
    ann_ids = coco.getAnnIds(imgIds=img_id)
    anns = coco.loadAnns(ann_ids)
    # Setup bbox
    bbox = np.zeros((100, 4))
    t_class = np.zeros((100, 1))
    # Count nb of bbox and crow bbox to filter later on
    nb_bbox = 0
    crowd_bbox = 0
    for a, ann in enumerate(anns):
        bbox_x, bbox_y, bbox_w, bbox_h = ann['bbox'] 
        # target class
        t_cls = ann["category_id"]
        if ann["iscrowd"]:
            crowd_bbox = 1
        # Convert bbox to xc, yc, w, h formast
        x_center = bbox_x + (bbox_w / 2)
        y_center = bbox_y + (bbox_h / 2)
        x_center = x_center / float(image_shape[1])
        y_center = y_center / float(image_shape[0])
        bbox_w = bbox_w / float(image_shape[1])
        bbox_h = bbox_h / float(image_shape[0])
        # Add bbox and class
        bbox[a+1] = [x_center, y_center, bbox_w, bbox_h]
        t_class[a+1][0] = t_cls
        nb_bbox += 1
    # Set bbox header
    bbox[0][0] = nb_bbox
    bbox = np.array(bbox)
    t_class = np.array(t_class)
    return bbox.astype(np.float32), t_class.astype(np.int32), crowd_bbox


def tf_get_coco(coco_dir, coco, img_id, train_val, augmentation, config):
    
    def get_coco(coco_id):
        # Load imag
        img = coco.loadImgs([coco_id])[0]
        # Load image
        data_type = "train2017" if train_val == "train" else "val2017"
        filne_name = img['file_name']
        image_path = f"{coco_dir}/{data_type}/{filne_name}"
        image = imageio.imread(image_path)
        # Graycale to RGB if needed
        if len(image.shape) == 2: image = gray2rgb(image)
        # Retrieve the image label
        t_bbox, t_class, is_crowd = get_coco_labels(coco, img['id'], image.shape, augmentation)
        # Apply augmentations
        image, t_bbox, t_class = detr_aug(image, t_bbox,  t_class, augmentation)
        # Normalized images
        image = processing.normalized_images(image, config)
        # Set type for tensorflow        
        image = image.astype(np.float32)
        t_bbox = t_bbox.astype(np.float32)
        t_class = t_class.astype(np.int64)
        return image, t_bbox, t_class, is_crowd

    return tf.numpy_function(get_coco,  [img_id], (tf.float32, tf.float32, tf.int64, tf.int64))


def load_coco(coco_dir, train_val, batch_size, config, augmentation=False):
    """
    """
    # Open annotation file and setup the coco object
    data_type = "train2017" if train_val == "train" else "val2017"
    ann_file = f"{coco_dir}/annotations/instances_{data_type}.json"
    coco = COCO(ann_file)

    # Setup the data pipeline
    img_ids = coco.getImgIds()
    shuffle(img_ids)
    dataset = tf.data.Dataset.from_tensor_slices(img_ids)
    dataset = dataset.shuffle(1000)
    dataset = dataset.map(lambda img_id: tf_get_coco(coco_dir, coco, img_id, train_val, augmentation, config), num_parallel_calls=tf.data.experimental.AUTOTUNE)
    dataset = dataset.filter(lambda imgs, tbbox, tclass, iscrowd: tbbox[0][0] > 0 and iscrowd != 1)
    dataset = dataset.map(lambda imgs, tbbox, tclass, iscrowd: (imgs, tbbox, tclass), num_parallel_calls=tf.data.experimental.AUTOTUNE)
    dataset = dataset.batch(batch_size, drop_remainder=True)
    dataset = dataset.prefetch(32)
    return dataset