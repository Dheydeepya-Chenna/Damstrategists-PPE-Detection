import json
import boto3
import cv2
import math
from flask import Flask, jsonify, request, render_template, send_file, url_for
import datetime
# import shutil
import os
import hashlib

app = Flask(__name__)

# videoFile = "input.mp4"
outputVideoFile = "output_ppe33.mp4"


AWS_REGION_NAME = 'AWS_REGION_NAME'
sns_topic_arn = "sns_topic_arn"
s3_bucket_ppe_frames = 's3_bucket_ppe_frames'
s3_bucket_input_videos ='s3_bucket_input_videos'

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION_NAME)

alerts_table = dynamodb.Table('PPE_Alerts')

# Create the Rekognition client
rekognition = boto3.client(
    'rekognition',
    region_name=AWS_REGION_NAME
)
sns = boto3.client('sns', region_name=AWS_REGION_NAME)
s3 = boto3.client('s3', region_name=AWS_REGION_NAME)


# Function to get list of videos from S3
def list_s3_videos():
    try:
        response = s3.list_objects_v2(Bucket=s3_bucket_input_videos)
        videos = [obj["Key"] for obj in response.get("Contents", []) if obj["Key"].endswith(".mp4")]
        return videos
    except Exception as e:
        print(f"Error fetching videos: {e}")
        return []
    
def get_presigned_url(video_name):
    response = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": s3_bucket_input_videos, "Key": video_name},
        ExpiresIn=3600  # URL expires in 1 hour
    )
    return response

@app.route("/get_video_url")
def get_video_url():
    video_name = request.args.get("video")

    if not video_name:
        return jsonify({"error": "No video specified"}), 400
    
    video_url = get_presigned_url(video_name)
    return jsonify({"video_url": video_url})

@app.route("/")
def index():
    videos = list_s3_videos()
    # return render_template("index.html", videos=videos, s3_bucket=s3_bucket_input_videos, s3_region=AWS_REGION_NAME)
    return render_template("index.html", videos=videos)

@app.route("/analyze", methods=["POST"])
def analyze():
    selected_video = request.json.get("video")
    if not selected_video:
        return jsonify({"error": "No video selected"}), 400

    analyzeVideo(selected_video)

    return jsonify({"message": f"Analyzing {selected_video}"}), 200



def analyzeVideo(videoFile):
  
    cap = cv2.VideoCapture(videoFile)
    frameRate = cap.get(cv2.CAP_PROP_FPS)  # Frames per second
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Create VideoWriter object to save the output video
    out = cv2.VideoWriter(outputVideoFile, cv2.VideoWriter_fourcc(*'mp4v'), frameRate, (width, height))

    def get_alerts():
        response = alerts_table.scan()
        alerts = response.get("Items", [])
        return alerts

    # def send_alert():
    #     message = f"⚠ PPE Violation Detected!(No helmet or gloves)"
    #     timestamp = datetime.datetime.utcnow().isoformat()
    #     sns.publish(TopicArn=sns_topic_arn, Message=message, Subject="PPE Violation Alert")
    #     print(f"🚨 Alert Sent: {message}")
    #     alerts_table.put_item(Item={
    #         "id": str(datetime.datetime.utcnow().timestamp()),
    #         "message": message,
    #         "timestamp": timestamp
    #     })

    
    def send_alert_with_snapshot(frame, frame_id):
        """Captures the frame, uploads it to S3, and sends an SNS alert with the image link."""
    
        # 1️⃣ Save the Frame Locally
        image_filename = f"ppe_violation_{frame_id}.jpg"
        cv2.imwrite(image_filename, frame)
    
        # 2️⃣ Upload to S3
        s3.upload_file(image_filename, s3_bucket_ppe_frames, image_filename)
    
        # 3️⃣ Generate Pre-Signed URL (Valid for 1 hour)
        image_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": s3_bucket_ppe_frames, "Key": image_filename},
            ExpiresIn=3600
        )
    
        # 4️⃣ Send SNS Alert with Image URL
        message = f"⚠ PPE Violation Detected! See image: {image_url}"
        sns.publish(TopicArn=sns_topic_arn, Message=message, Subject="PPE Violation Alert")

        print(f"🚨 Alert Sent: {message}")

    person_boxes = {}  # Store detected persons across frames
    alerted_persons ={}

    def generate_person_id(x1, y1, x2, y2):
        """Generate a unique ID for each person based on their bounding box coordinates."""
        return hashlib.md5(f"{x1},{y1},{x2},{y2}".encode()).hexdigest()
    
    while cap.isOpened():
        frameId = int(cap.get(cv2.CAP_PROP_POS_FRAMES))  # Current frame number
        ret, frame = cap.read()

        if not ret:  # End of video
            break

        if frame is None:
            continue

        if frameId % math.floor(frameRate) == 0:  
            hasFrame, imageBytes = cv2.imencode(".jpg", frame)
            if hasFrame:
                try:
                    response = rekognition.detect_protective_equipment(
                        Image={'Bytes': imageBytes.tobytes()}
                    )

                    person_boxes.clear()  

                    for person in response.get("Persons", []):
                        person_bbox = person.get("BoundingBox", {})
                        x1 = int(person_bbox['Left'] * width)
                        y1 = int(person_bbox['Top'] * height)
                        x2 = int((person_bbox['Left'] + person_bbox['Width']) * width)
                        y2 = int((person_bbox['Top'] + person_bbox['Height']) * height)

                        has_helmet = False
                        has_gloves = False
                        has_mask = False  
                        equipment_boxes = []

                        for body_part in person.get('BodyParts', []):
                            for detection in body_part.get('EquipmentDetections', []):
                                equip_type = detection['Type']
                                confidence = detection['Confidence']

                                if confidence < 80:  # Ignore low confidence detections
                                    continue

                                equip_bbox = detection['BoundingBox']
                                ex1 = int(equip_bbox['Left'] * width)
                                ey1 = int(equip_bbox['Top'] * height)
                                ex2 = int((equip_bbox['Left'] + equip_bbox['Width']) * width)
                                ey2 = int((equip_bbox['Top'] + equip_bbox['Height']) * height)

                                equipment_boxes.append((ex1, ey1, ex2, ey2, (0, 255, 0)))  # Green for detected PPE

                                if equip_type == 'HEAD_COVER':
                                    has_helmet = True
                                if equip_type == 'HAND_COVER':
                                    has_gloves = True
                                if equip_type == 'FACE_COVER':
                                    has_mask = True

                        # If missing helmet or gloves, mark person in RED, otherwise GREEN
                        person_color = (0, 255, 0) if has_helmet and has_gloves and has_mask else (0, 0, 255) 
                        person_id = generate_person_id(x1, y1, x2, y2)
                        person_boxes[frameId] = (x1, y1, x2, y2, person_color, equipment_boxes)
                        # if(person_color == (0, 0, 255)):
                        #     # send_alert()
                        #     send_alert_with_snapshot(frame, frameId)
                except Exception as e:
                    print(f"Error calling Rekognition: {e}")
                    continue  # Continue processing the next frame even if there's an error

        # Draw stored rectangles from the last detection
        for key, (x1, y1, x2, y2, person_color, equipment_boxes) in person_boxes.items():
            # Draw person bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), person_color, 3)
            
            # Draw equipment bounding boxes
            for ex1, ey1, ex2, ey2, equip_color in equipment_boxes:
                cv2.rectangle(frame, (ex1, ey1), (ex2, ey2), equip_color, 2)

        # Write the frame with rectangles to the output video file
        out.write(frame)
        # if(person_color == (0, 0, 255)) and person_id not in alerted_persons:
        #     send_alert_with_snapshot(frame, frameId)

    # Clean up
    cap.release()
    out.release()
    # cv2.destroyAllWindows()
    # data = get_alerts()
    # print(data)
    print("Video processing complete")
    # save_video_locally()



if __name__ == '__main__':
    app.run(debug=True)