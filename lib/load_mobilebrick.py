import torch
import torch.nn.functional as F
import cv2 as cv
import numpy as np
import os
from glob import glob
from icecream import ic
from scipy.spatial.transform import Rotation as Rot
from scipy.spatial.transform import Slerp
import imageio

# This function is borrowed from IDR: https://github.com/lioryariv/idr
def load_K_Rt_from_P(filename, P=None):
    if P is None:
        lines = open(filename).read().splitlines()
        if len(lines) == 4:
            lines = lines[1:]
        lines = [[x[0], x[1], x[2], x[3]] for x in (x.split(" ") for x in lines)]
        P = np.asarray(lines).astype(np.float32).squeeze()

    out = cv.decomposeProjectionMatrix(P)
    K = out[0]
    R = out[1]
    t = out[2]

    K = K / K[2, 2]
    intrinsics = np.eye(4)
    intrinsics[:3, :3] = K

    pose = np.eye(4, dtype=np.float32)
    pose[:3, :3] = R.transpose()
    pose[:3, 3] = (t[:3] / t[3])[:, 0]

    return intrinsics, pose


def load_mobilebrick_data(basedir, normalize=True, reso_level=2, mask=False, white_bg=False):

    rgb_paths = sorted(glob(os.path.join(basedir, 'image', '*jpg')))
    mask_paths = sorted(glob(os.path.join(basedir, 'mask', '*png')))
    render_cameras_name = 'cameras.npz'
    camera_dict = np.load(os.path.join(basedir, render_cameras_name))
    world_mats_np = [camera_dict['world_mat_%d' % idx].astype(np.float32) for idx in range(len(rgb_paths))]
    if normalize:
        scale_mats_np = [camera_dict['scale_mat_%d' % idx].astype(np.float32) for idx in range(len(rgb_paths))]
    else:
        scale_mats_np = None
    all_intrinsics = []
    all_poses = []
    all_imgs = []
    all_masks = []
    for i, (world_mat, im_name) in enumerate(zip(world_mats_np, rgb_paths)):
        if normalize:
            P = world_mat @ scale_mats_np[i]
        else:
            P = world_mat
        P = P[:3, :4]
        intrinsics, pose = load_K_Rt_from_P(None, P)
        all_intrinsics.append(intrinsics)
        all_poses.append(pose)
        if len(mask_paths) > 0:
            mask_ = (imageio.imread(mask_paths[i]) / 255.).astype(np.float32)
            if mask_.ndim == 3:
                all_masks.append(mask_[...,:3])
            else:
                all_masks.append(mask_[...,None])
        all_imgs.append((imageio.imread(im_name) / 255.).astype(np.float32))
    imgs = np.stack(all_imgs, 0)
    poses = np.stack(all_poses, 0)
    H, W = imgs[0].shape[:2]
    K = all_intrinsics[0]
    focal = all_intrinsics[0][0,0]
    print("Date original shape: ", H, W)
    masks = np.stack(all_masks, 0)
    if mask:
        assert len(mask_paths) > 0
        bg = 1. if white_bg else 0.
        imgs = imgs * masks + bg * (1 - masks)

    if reso_level > 1:
        H, W = int(H / reso_level), int(W / reso_level)
        imgs =  F.interpolate(torch.from_numpy(imgs).permute(0,3,1,2), size=(H, W)).permute(0,2,3,1).numpy()
        if masks is not None:
            masks =  F.interpolate(torch.from_numpy(masks).permute(0,3,1,2), size=(H, W)).permute(0,2,3,1).numpy()
        K[:2] /= reso_level
        focal /= reso_level

    # this is to randomly fetch images.
    i_test = [i for i in range(len(imgs)) if (i-3)%8==0]
    i_val = i_test
    i_train = list(set(np.arange(len(imgs))) - set(i_test))

    i_split = [np.array(i_train), np.array(i_val), np.array(i_test)]

    render_poses = poses[i_split[-1]]
    return imgs, poses, render_poses, [H, W, focal], K, i_split, scale_mats_np[0], masks
