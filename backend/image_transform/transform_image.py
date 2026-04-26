from PIL import Image, ImageOps

try:
    from .palettes import (
        waveshare_e6_calibrated,
        waveshare_e6_empirical,
        waveshare_e6_ideal,
    )
except ImportError:
    from palettes import waveshare_e6_calibrated, waveshare_e6_empirical, waveshare_e6_ideal


def _prepared_image(image: Image.Image, target: tuple[int, int] | None = None) -> Image.Image:
    image = ImageOps.exif_transpose(image)

    if image.mode != "RGB":
        image = image.convert("RGB")

    if target is None:
        width, height = image.size
        aspect = width / height
        target = (400, 600) if aspect < 1 else (600, 400)

    return ImageOps.fit(
        image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )


def _palette_image(palette: list) -> Image.Image:
    palette_img = Image.new("P", (1, 1), 0)
    palette_img.putpalette(sum(palette, ()))
    return palette_img


def transform_image_pair(
    image: Image.Image,
    preview_palette: list,
    display_palette: list,
    target: tuple[int, int] | None = None,
) -> tuple[Image.Image, Image.Image]:
    prepared = _prepared_image(image, target)
    dithered = prepared.quantize(
        colors=len(preview_palette),
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=_palette_image(preview_palette),
    )

    display_indexed = Image.new("P", dithered.size)
    display_indexed.putpalette(sum(display_palette, ()))
    display_indexed.frombytes(dithered.tobytes())

    return dithered.convert("RGB"), display_indexed.convert("RGB")


def transform_image(image: Image.Image, palette: list, target: tuple[int, int] | None = None) -> Image.Image:
    """
    Transforms the input image to match the given palette.

    Args:
        image (Image.Image): The input image to be transformed.
        palette (list): A list of RGB tuples representing the target palette.

    Returns:
        Image.Image: The transformed image.
    """
    preview, _ = transform_image_pair(image, palette, palette, target)
    return preview


if __name__ == "__main__":
    # Example usage
    image_name = "Graphene_Render05.png"  # Replace with your image name
    input_image_path = f"images_raw/{image_name}"  # Replace with your input image path
    output_image_path = (
        f"images/dith_{image_name}"  # Replace with your desired output image path
    )

    # Load the input image
    input_image = Image.open(input_image_path)

    # Transform the image using the ideal palette
    # transformed_image = transform_image(input_image, waveshare_e6_empirical)
    transformed_image = transform_image(input_image, waveshare_e6_ideal)
    # to rgb
    # Save the transformed image
    transformed_image.save(output_image_path)
    print(f"Transformed image saved to {output_image_path}")
