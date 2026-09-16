"""Default segmentation model for the iPad correction demo.

Replace only ``segment`` to connect this editor to another project. The
returned mask must contain integer class IDs matching the returned names.
"""

from PIL import Image
import numpy as np
import torch
import torch.nn.functional as functional
from torchvision.models.segmentation import (
    DeepLabV3_MobileNet_V3_Large_Weights,
    deeplabv3_mobilenet_v3_large,
)


def segment(image: Image.Image) -> tuple[np.ndarray, list[str]]:
    """Segment an RGB image with the pretrained DeepLabV3 MobileNet model.

    Args:
        image: RGB Pillow image at the editor's working resolution.

    Returns:
        A height-by-width uint8 array of class IDs and the class names in ID
        order. Class zero is background.
    """
    weights = DeepLabV3_MobileNet_V3_Large_Weights.DEFAULT
    model = deeplabv3_mobilenet_v3_large(weights=weights).eval()
    input_tensor = weights.transforms()(image).unsqueeze(0)

    with torch.inference_mode():
        scores = model(input_tensor)["out"]
        # The model runs on a smaller image; restore one class prediction per
        # editor pixel before choosing the most likely class.
        scores = functional.interpolate(
            scores, size=(image.height, image.width), mode="bilinear", align_corners=False
        )
        mask = scores.argmax(dim=1).squeeze(0).byte().cpu().numpy()

    return mask, list(weights.meta["categories"])
