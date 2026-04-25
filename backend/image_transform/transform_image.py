from PIL import Image, ImageOps

try:
    from .palettes import waveshare_e6_ideal, waveshare_e6_empirical
except ImportError:
    from palettes import waveshare_e6_ideal, waveshare_e6_empirical


def transform_image(image: Image.Image, palette: list) -> Image.Image:
    """
    Transforms the input image to match the given palette.

    Args:
        image (Image.Image): The input image to be transformed.
        palette (list): A list of RGB tuples representing the target palette.

    Returns:
        Image.Image: The transformed image.
    """
    image = ImageOps.exif_transpose(image)

    # Convert the image to RGB mode if it's not already
    if image.mode != "RGB":
        image = image.convert("RGB")

    # Create a new image with 400 x 600 or 600 x 400 dimensions, depending on the aspect ratio of the input image
    width, height = image.size

    aspect = width / height
    target = (400, 600) if aspect < 1 else (600, 400)

    prepared = ImageOps.fit(
        image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )
    palette_img = Image.new("P", (1, 1), 0)
    palette_img.putpalette(sum(palette, ()))
    dithered = prepared.quantize(
        colors=len(palette),
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=palette_img,
    )
    return dithered.convert("RGB")


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
