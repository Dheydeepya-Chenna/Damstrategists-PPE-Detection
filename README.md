# Damstrategists-PPE-Detection
Personal Protective Equipment detection in videos using Amazon Rekognition, S3, SNS, DynamoDb services.

Damstrategists-PPE-Detection displays list of videos, which are uploaded in the s3 bucket (input video should be uploaded in the s3 bucket).
On selecting the video from the UI and clicking on analyze, PPE detection starts and detect if people are wearing the required protective equipment, such as face covers , head covers, and hand covers using AWS Rekognition.
When a PPE violation is detected we are sending email notification/alerts to the admin using AWS SNS service.
In the email we are sending details of the violation by sharing the URL to the image(frame) where PPE is violated by the person. To share this information we are saving the frames/images where PPE is violated in an s3 bucket and sharing the saved image URL.
And for the further processing and reference we are also saving the alerts information in the AWS DynamoDB along with the timestamps. 
 
