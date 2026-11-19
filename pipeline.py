import os
import csv
import json
import hashlib
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from PIL import Image, ImageStat, ImageFilter, ImageOps


# Default paths (used when running from command line)
DATA_PATH = "data"
PROCESSED_PATH = "processed_data"
REPORT_PATH = "reports"

IMAGE_SIZE = (128, 128)
SUPPORTED_FORMATS = (".jpg", ".jpeg", ".png")

MIN_IMAGE_DIMENSION = 128
DARK_THRESHOLD = 45
BRIGHT_THRESHOLD = 210
BLUR_THRESHOLD = 8.0

SIMILARITY_THRESHOLD = 0.95


def get_classes(data_path=None):
    if data_path is None:
        data_path = DATA_PATH

    if not os.path.isdir(data_path):
        return []

    return sorted([
        folder for folder in os.listdir(data_path)
        if os.path.isdir(os.path.join(data_path, folder))
    ])


def get_hash(file_path):
    hasher = hashlib.md5()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def analyze_image_quality(image):
    width, height = image.size
    grayscale = image.convert("L")

    brightness = ImageStat.Stat(grayscale).mean[0]

    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).mean[0]

    issues = []

    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        issues.append("Low resolution")

    if brightness < DARK_THRESHOLD:
        issues.append("Too dark")
    elif brightness > BRIGHT_THRESHOLD:
        issues.append("Too bright")

    if sharpness < BLUR_THRESHOLD:
        issues.append("Potentially blurry")

    return {
        "width": width,
        "height": height,
        "brightness": round(brightness, 2),
        "sharpness": round(sharpness, 2),
        "issues": issues
    }


def validate_images(class_name, seen_hashes, data_path=None):
    if data_path is None:
        data_path = DATA_PATH

    folder = os.path.join(data_path, class_name)

    valid_files = []
    invalid_count = 0
    duplicate_count = 0
    unsupported_count = 0

    quality_records = []
    image_records = []

    for filename in sorted(os.listdir(folder)):
        file_path = os.path.join(folder, filename)

        if not os.path.isfile(file_path):
            continue

        record = {
            "class": class_name,
            "filename": filename,
            "relative_path": os.path.join(class_name, filename),
            "status": "",
            "hash": "",
            "width": "",
            "height": "",
            "brightness": "",
            "sharpness": "",
            "issues": "",
            "processed": False,
            "processed_path": "",
            "processing_error": ""
        }

        if not filename.lower().endswith(SUPPORTED_FORMATS):
            unsupported_count += 1
            record["status"] = "Unsupported"
            record["issues"] = "Unsupported file format"
            image_records.append(record)
            continue

        try:
            with Image.open(file_path) as image:
                image.verify()

            with Image.open(file_path) as image:
                image = ImageOps.exif_transpose(image)
                image = image.convert("RGB")
                quality = analyze_image_quality(image)

            file_hash = get_hash(file_path)

            record["hash"] = file_hash
            record["width"] = quality["width"]
            record["height"] = quality["height"]
            record["brightness"] = quality["brightness"]
            record["sharpness"] = quality["sharpness"]
            record["issues"] = "; ".join(quality["issues"])

            if file_hash in seen_hashes:
                duplicate_count += 1
                record["status"] = "Duplicate"

            else:
                seen_hashes[file_hash] = record["relative_path"]
                valid_files.append(filename)
                record["status"] = "Valid"

            if quality["issues"]:
                quality_records.append({
                    "class": class_name,
                    "filename": filename,
                    **quality
                })

            image_records.append(record)

        except Exception as error:
            invalid_count += 1
            record["status"] = "Invalid"
            record["issues"] = str(error)
            image_records.append(record)

    return (
        valid_files,
        invalid_count,
        duplicate_count,
        unsupported_count,
        quality_records,
        image_records
    )


def process_images(class_name, valid_files, image_records, data_path=None, processed_path=None):
    if data_path is None:
        data_path = DATA_PATH
    if processed_path is None:
        processed_path = PROCESSED_PATH

    input_folder = os.path.join(data_path, class_name)
    output_folder = os.path.join(processed_path, class_name)

    os.makedirs(output_folder, exist_ok=True)

    processed_count = 0
    processed_paths = []

    records_by_name = {
        record["filename"]: record
        for record in image_records
        if record["class"] == class_name
    }

    for filename in valid_files:
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)

        try:
            with Image.open(input_path) as image:
                image = ImageOps.exif_transpose(image)
                image = image.convert("RGB")

                image.thumbnail(IMAGE_SIZE, Image.Resampling.LANCZOS)

                canvas = Image.new("RGB", IMAGE_SIZE, (0, 0, 0))

                x = (IMAGE_SIZE[0] - image.width) // 2
                y = (IMAGE_SIZE[1] - image.height) // 2

                canvas.paste(image, (x, y))
                canvas.save(output_path)

            processed_count += 1

            processed_paths.append({
                "name": f"{class_name}/{filename}",
                "path": output_path
            })

            if filename in records_by_name:
                records_by_name[filename]["processed"] = True
                records_by_name[filename]["processed_path"] = output_path

        except Exception as error:
            if filename in records_by_name:
                records_by_name[filename]["processing_error"] = str(error)

    return processed_count, processed_paths


def find_similar_images(processed_paths, report_path=None):
    if report_path is None:
        report_path = REPORT_PATH

    report_file = os.path.join(report_path, "similar_images.txt")

    results = {
        "status": "not_run",
        "similar_pairs": 0,
        "message": "",
        "pairs": []
    }

    if len(processed_paths) < 2:
        results["message"] = "Not enough images for similarity analysis."
        return results

    try:
        import torch
        from torchvision import models

        weights = models.MobileNet_V2_Weights.DEFAULT
        model = models.mobilenet_v2(weights=weights)
        model.classifier = torch.nn.Identity()
        model.eval()

        transform = weights.transforms()

        names = []
        vectors = []

        with torch.no_grad():
            for item in processed_paths:
                try:
                    with Image.open(item["path"]) as image:
                        image = image.convert("RGB")
                        tensor = transform(image).unsqueeze(0)

                    features = model(tensor)[0]
                    features = features / features.norm().clamp(min=1e-12)

                    vectors.append(features)
                    names.append(item["name"])

                except Exception:
                    pass

        if len(vectors) < 2:
            results["message"] = "Not enough readable images for comparison."
            return results

        vectors = torch.stack(vectors)
        similar_pairs = []
        block_size = 256

        with torch.no_grad():
            for start in range(0, len(names), block_size):
                end = min(start + block_size, len(names))
                similarity_block = vectors[start:end] @ vectors.T

                for local_index in range(end - start):
                    i = start + local_index
                    for j in range(i + 1, len(names)):
                        score = similarity_block[local_index, j].item()
                        if score >= SIMILARITY_THRESHOLD:
                            similar_pairs.append({
                                "image_1": names[i],
                                "image_2": names[j],
                                "similarity": round(score, 4)
                            })

        with open(report_file, "w", encoding="utf-8") as file:
            file.write("SIMILAR IMAGE ANALYSIS\n")
            file.write("=" * 50 + "\n\n")
            file.write(f"Images compared: {len(names)}\n")
            file.write(f"Similarity threshold: {SIMILARITY_THRESHOLD}\n\n")

            if not similar_pairs:
                file.write("No potentially similar image pairs found.\n")

            for pair in similar_pairs:
                file.write(
                    f"{pair['image_1']}  <->  {pair['image_2']}\n"
                    f"Similarity: {pair['similarity']}\n\n"
                )

        results["status"] = "completed"
        results["similar_pairs"] = len(similar_pairs)
        results["pairs"] = similar_pairs
        results["message"] = "Similarity analysis completed."

    except ImportError:
        results["status"] = "skipped"
        results["message"] = "PyTorch or TorchVision is not installed."

    except Exception as error:
        results["status"] = "failed"
        results["message"] = str(error)

    return results


def evaluate_dataset(report_data, quality_records):
    class_counts = {
        name: data["valid"]
        for name, data in report_data.items()
    }

    counts = list(class_counts.values())

    if len(counts) < 2:
        balance_status = "Not applicable - fewer than two classes"
        imbalanced = False
        balance_ratio = None
    else:
        smallest = min(counts)
        largest = max(counts)

        if smallest == 0:
            balance_ratio = None
            imbalanced = True
        else:
            balance_ratio = round(largest / smallest, 2)
            imbalanced = balance_ratio > 1.5

        balance_status = "Imbalanced" if imbalanced else "Balanced"

    total_valid = sum(data["valid"] for data in report_data.values())
    total_invalid = sum(data["invalid"] for data in report_data.values())
    total_duplicates = sum(data["duplicates"] for data in report_data.values())
    total_unsupported = sum(data["unsupported"] for data in report_data.values())
    total_processed = sum(data["processed"] for data in report_data.values())

    issue_counts = {
        "Low resolution": 0,
        "Too dark": 0,
        "Too bright": 0,
        "Potentially blurry": 0
    }

    for record in quality_records:
        for issue in record["issues"]:
            issue_counts[issue] += 1

    recommendations = []

    if total_invalid:
        recommendations.append("Review the corrupted images that were skipped.")
    if total_duplicates:
        recommendations.append("Review duplicate images to reduce unnecessary redundancy.")
    if total_unsupported:
        recommendations.append("Check unsupported files if they are intended to be images.")
    if imbalanced:
        recommendations.append(
            "Consider adding more images to the smaller classes to improve class balance."
        )
    if sum(issue_counts.values()):
        recommendations.append("Review images flagged for potential quality issues.")
    if not recommendations:
        recommendations.append("No major issues were detected by the current checks.")

    if total_processed == 0:
        dataset_status = "No images were successfully processed."
    elif (total_invalid or total_duplicates or imbalanced or sum(issue_counts.values())):
        dataset_status = "Review recommended."
    else:
        dataset_status = "No major issues detected."

    return {
        "total_valid": total_valid,
        "total_invalid": total_invalid,
        "total_duplicates": total_duplicates,
        "total_unsupported": total_unsupported,
        "total_processed": total_processed,
        "class_balance": balance_status,
        "class_balance_ratio": balance_ratio,
        "class_counts": class_counts,
        "quality_issues": issue_counts,
        "total_quality_flags": sum(issue_counts.values()),
        "dataset_status": dataset_status,
        "recommendations": recommendations
    }


def generate_image_manifest(image_records, report_path=None):
    if report_path is None:
        report_path = REPORT_PATH

    os.makedirs(report_path, exist_ok=True)

    manifest_file = os.path.join(report_path, "image_manifest.csv")

    fieldnames = [
        "class", "filename", "relative_path", "status", "hash",
        "width", "height", "brightness", "sharpness", "issues",
        "processed", "processed_path", "processing_error"
    ]

    with open(manifest_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(image_records)


def generate_reports(report_data, evaluation, quality_records, similarity, image_records, report_path=None):
    if report_path is None:
        report_path = REPORT_PATH

    os.makedirs(report_path, exist_ok=True)

    report_file = os.path.join(report_path, "report.txt")

    with open(report_file, "w", encoding="utf-8") as file:
        file.write("IMAGE DATASET ANALYSIS REPORT\n")
        file.write("=" * 55 + "\n\n")

        for class_name, data in report_data.items():
            file.write(f"CLASS: {class_name}\n")
            file.write("-" * 40 + "\n")
            file.write(f"Valid images: {data['valid']}\n")
            file.write(f"Invalid images: {data['invalid']}\n")
            file.write(f"Duplicates skipped: {data['duplicates']}\n")
            file.write(f"Unsupported files: {data['unsupported']}\n")
            file.write(f"Processed images: {data['processed']}\n\n")

        file.write("DATASET SUMMARY\n")
        file.write("=" * 55 + "\n")

        for key, value in evaluation.items():
            if key not in ("class_counts", "quality_issues", "recommendations"):
                file.write(f"{key.replace('_', ' ').title()}: {value}\n")

        file.write("\nIMAGE QUALITY ISSUES\n")
        for issue, count in evaluation["quality_issues"].items():
            file.write(f"{issue}: {count}\n")

        file.write("\nRECOMMENDATIONS\n")
        for recommendation in evaluation["recommendations"]:
            file.write(f"- {recommendation}\n")

        file.write("\nSIMILARITY ANALYSIS\n")
        file.write(f"Status: {similarity['status']}\n")
        file.write(f"Similar pairs: {similarity['similar_pairs']}\n")
        file.write(f"Message: {similarity['message']}\n")

        file.write("\nIMAGE AUDIT SUMMARY\n")
        file.write(f"Total audited files: {len(image_records)}\n")

    json_file = os.path.join(report_path, "report.json")

    json_data = {
        "classes": report_data,
        "evaluation": evaluation,
        "quality_records": [
            {k: (list(v) if isinstance(v, list) else v) for k, v in r.items()}
            for r in quality_records
        ],
        "image_records": image_records,
        "similarity_analysis": {
            k: v for k, v in similarity.items()
            if k != "pairs"
        }
    }

    with open(json_file, "w", encoding="utf-8") as file:
        json.dump(json_data, file, indent=4)

    csv_file = os.path.join(report_path, "class_summary.csv")

    with open(csv_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Class", "Valid", "Invalid", "Duplicates", "Unsupported", "Processed"])
        for class_name, data in report_data.items():
            writer.writerow([
                class_name, data["valid"], data["invalid"],
                data["duplicates"], data["unsupported"], data["processed"]
            ])


def generate_charts(report_data, evaluation, image_records, report_path=None):
    if report_path is None:
        report_path = REPORT_PATH

    chart_folder = os.path.join(report_path, "charts")
    os.makedirs(chart_folder, exist_ok=True)

    classes = list(report_data.keys())
    valid_counts = [report_data[name]["valid"] for name in classes]

    # Class distribution bar chart
    plt.figure(figsize=(9, 5))
    bars = plt.bar(classes, valid_counts)
    plt.title("Dataset Class Distribution")
    plt.xlabel("Classes")
    plt.ylabel("Valid Images")
    plt.xticks(rotation=30, ha="right")
    for bar, count in zip(bars, valid_counts):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), str(count), ha="center", va="bottom")
    plt.tight_layout()
    plt.savefig(os.path.join(chart_folder, "class_distribution.png"))
    plt.close()

    # Audit status chart
    audit_labels = ["Valid", "Invalid", "Duplicates", "Unsupported"]
    audit_values = [
        evaluation["total_valid"],
        evaluation["total_invalid"],
        evaluation["total_duplicates"],
        evaluation["total_unsupported"]
    ]
    plt.figure(figsize=(8, 5))
    bars = plt.bar(audit_labels, audit_values)
    plt.title("Image Audit Status")
    plt.xlabel("Image Status")
    plt.ylabel("Number of Files")
    for bar, count in zip(bars, audit_values):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), str(count), ha="center", va="bottom")
    plt.tight_layout()
    plt.savefig(os.path.join(chart_folder, "image_audit_status.png"))
    plt.close()

    # Quality issues chart
    quality_data = evaluation["quality_issues"]
    plt.figure(figsize=(9, 5))
    bars = plt.bar(list(quality_data.keys()), list(quality_data.values()))
    plt.title("Image Quality Analysis")
    plt.xlabel("Quality Issues")
    plt.ylabel("Flagged Images")
    plt.xticks(rotation=25, ha="right")
    for bar, count in zip(bars, quality_data.values()):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), str(count), ha="center", va="bottom")
    plt.tight_layout()
    plt.savefig(os.path.join(chart_folder, "image_quality.png"))
    plt.close()

    valid_records = [r for r in image_records if r["status"] == "Valid"]

    # Brightness histogram
    brightness_values = [float(r["brightness"]) for r in valid_records if r["brightness"] != ""]
    if brightness_values:
        plt.figure(figsize=(8, 5))
        plt.hist(brightness_values, bins=20, edgecolor="black")
        plt.title("Image Brightness Distribution")
        plt.xlabel("Brightness")
        plt.ylabel("Number of Images")
        plt.tight_layout()
        plt.savefig(os.path.join(chart_folder, "brightness_distribution.png"))
        plt.close()

    # Sharpness histogram
    sharpness_values = [float(r["sharpness"]) for r in valid_records if r["sharpness"] != ""]
    if sharpness_values:
        plt.figure(figsize=(8, 5))
        plt.hist(sharpness_values, bins=20, edgecolor="black")
        plt.title("Image Sharpness Distribution")
        plt.xlabel("Sharpness")
        plt.ylabel("Number of Images")
        plt.tight_layout()
        plt.savefig(os.path.join(chart_folder, "sharpness_distribution.png"))
        plt.close()

    # Width histogram
    width_values = [int(r["width"]) for r in valid_records if r["width"] != ""]
    if width_values:
        plt.figure(figsize=(8, 5))
        plt.hist(width_values, bins=20, edgecolor="black")
        plt.title("Image Width Distribution")
        plt.xlabel("Width in Pixels")
        plt.ylabel("Number of Images")
        plt.tight_layout()
        plt.savefig(os.path.join(chart_folder, "width_distribution.png"))
        plt.close()

    # Height histogram
    height_values = [int(r["height"]) for r in valid_records if r["height"] != ""]
    if height_values:
        plt.figure(figsize=(8, 5))
        plt.hist(height_values, bins=20, edgecolor="black")
        plt.title("Image Height Distribution")
        plt.xlabel("Height in Pixels")
        plt.ylabel("Number of Images")
        plt.tight_layout()
        plt.savefig(os.path.join(chart_folder, "height_distribution.png"))
        plt.close()

    # Class share pie chart
    if sum(valid_counts) > 0:
        plt.figure(figsize=(8, 7))
        plt.pie(valid_counts, labels=classes, autopct="%1.1f%%", startangle=90)
        plt.title("Dataset Class Share")
        plt.tight_layout()
        plt.savefig(os.path.join(chart_folder, "class_share.png"))
        plt.close()


def run_pipeline(
    data_path=None,
    processed_path=None,
    report_path=None,
    run_similarity=True,
    log_callback=None
):
    """
    Run the full dataset analysis pipeline.

    Parameters
    ----------
    data_path       : Path to the dataset folder (default: DATA_PATH constant)
    processed_path  : Output folder for processed images (default: PROCESSED_PATH)
    report_path     : Output folder for reports and charts (default: REPORT_PATH)
    run_similarity  : Whether to run the similarity analysis (default: True)
    log_callback    : Optional callable(str) for real-time log messages
    """
    if data_path is None:
        data_path = DATA_PATH
    if processed_path is None:
        processed_path = PROCESSED_PATH
    if report_path is None:
        report_path = REPORT_PATH

    def log(msg):
        print(msg)
        if log_callback:
            log_callback(str(msg))

    log("\nIMAGE DATASET ANALYSIS PIPELINE")
    log("=" * 50)

    if not os.path.isdir(data_path):
        log("Error: data directory does not exist.")
        return None

    classes = get_classes(data_path)

    if not classes:
        log("No class folders found inside the dataset directory.")
        return None

    if os.path.exists(processed_path):
        shutil.rmtree(processed_path)

    if os.path.exists(report_path):
        shutil.rmtree(report_path)

    os.makedirs(processed_path, exist_ok=True)
    os.makedirs(report_path, exist_ok=True)

    report_data = {}
    quality_records = []
    all_image_records = []
    all_processed_paths = []

    seen_hashes = {}

    for class_name in classes:
        log(f"\nProcessing class: {class_name}")

        (
            valid_files,
            invalid_count,
            duplicate_count,
            unsupported_count,
            class_quality_records,
            class_image_records
        ) = validate_images(class_name, seen_hashes, data_path=data_path)

        processed_count, processed_paths = process_images(
            class_name, valid_files, class_image_records,
            data_path=data_path, processed_path=processed_path
        )

        report_data[class_name] = {
            "valid": len(valid_files),
            "invalid": invalid_count,
            "duplicates": duplicate_count,
            "unsupported": unsupported_count,
            "processed": processed_count
        }

        quality_records.extend(class_quality_records)
        all_image_records.extend(class_image_records)
        all_processed_paths.extend(processed_paths)

        log(f"  Valid: {len(valid_files)}")
        log(f"  Invalid: {invalid_count}")
        log(f"  Duplicates: {duplicate_count}")
        log(f"  Unsupported: {unsupported_count}")
        log(f"  Processed: {processed_count}")

    evaluation = evaluate_dataset(report_data, quality_records)

    if run_similarity:
        log("\nStarting similarity analysis...")
        similarity = find_similar_images(all_processed_paths, report_path=report_path)
        log(similarity["message"])
    else:
        log("\nSimilarity analysis skipped.")
        similarity = {
            "status": "skipped",
            "similar_pairs": 0,
            "message": "Similarity analysis was not requested.",
            "pairs": []
        }

    log("\nGenerating image manifest...")
    generate_image_manifest(all_image_records, report_path=report_path)

    log("Generating reports...")
    generate_reports(
        report_data, evaluation, quality_records,
        similarity, all_image_records, report_path=report_path
    )

    log("Generating charts...")
    generate_charts(report_data, evaluation, all_image_records, report_path=report_path)

    results = {
        "classes": report_data,
        "evaluation": evaluation,
        "quality_records": quality_records,
        "image_records": all_image_records,
        "similarity_analysis": similarity
    }

    log("\n" + "=" * 50)
    log("PIPELINE COMPLETED")
    log("=" * 50)
    log(f"Dataset status: {evaluation['dataset_status']}")
    log(f"Total processed: {evaluation['total_processed']}")
    log(f"Quality flags: {evaluation['total_quality_flags']}")
    log(f"Similar image pairs: {similarity['similar_pairs']}")

    return results


if __name__ == "__main__":
    run_pipeline()
