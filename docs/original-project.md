> This is the README of the original 2021 version (Flask + MongoDB + TensorFlow YOLOv4), kept for reference. The code for that version is in git history at the `v1-legacy` tag.

This is a Project I completed in my Under-Grad in Information Technology from Mumbai University
# CrowdCounting
# Real-time Crowd Counting Application with Live Analytics

## Authors:
- Mubin Modi, Student
- Zaid Marouf, Student
- Anvay Wankhede, Student
- Dr. Shabina Sayed, Faculty

![demo](https://github.com/mubinmodi/Crowdcounting/assets/47493706/e1a5d00f-e6cf-4162-b5bb-e5b37161cd80)



## Affiliation:
Dept. of Information Technology Engineering, M.H. Saboo Siddik College of Engineering, Mumbai, India


## Abstract:
The increase in population and the development of countries have led to an increase in crowd occurrences worldwide, necessitating the creation of a crowd analysis tool for security and crowd management. Understanding crowd dynamics and congestion circumstances at crowded scenes is critical for public safety. This paper proposes a Real-time Crowd Counting application with selective detection using YOLOv4, leveraging computer vision and neural networks for crowd counting analytics. Key features include live analytics and selective detection to address security concerns and crowd management.

## Introduction:
Understanding crowd behavior is crucial, especially in environments such as sports events, festivals, and mass gatherings. Crowd analysis is challenging due to complex pedestrian behavior, which poses safety and security challenges. This application focuses on sparse crowd scenarios in locations like malls, hospitals, and schools. Leveraging YOLOv4 for object detection, the system aims to provide accurate real-time crowd counting and analytics to aid security and management decisions.

## Methodology:
The application is hosted locally using Flask and can be deployed on any cloud service. Users can connect their network cameras, providing input for crowd counting. Object detection is performed using YOLOv4, a real-time recognition system trained on the COCO dataset, chosen for its accuracy and efficiency. Selective detection is introduced to address count duplication issues in overlapping camera coverage areas. Live analytics are generated using Server-sent Events, offering users real-time insights into crowd dynamics.

![image](https://github.com/mubinmodi/Crowdcounting/assets/47493706/4cdb3658-cf75-4b06-a7dd-348b3b405b18)

 This diagram appears to represent a system flowchart for a crowd counting application, detailing how the different modules of the system interact with each other. Here's a step-by-step explanation:

1. **Configuration Module**:
   - **Actor**: This is the user who interacts with the system.
   - **Action**: The user creates an account or logs into an existing account.
   - **Data Storage**: All user information is stored in the `mongodb` database.
   - **Camera Setup**: The user sets up cameras if not already set up. The IP addresses of the cameras are sent as input to the system.
   - **Zone Setup**: The user sends the zone coordinates and other edited data, such as detection areas, to the system.

2. **Crowd Counting Module**:
   - **Video Stream**: The system starts the video stream from the cameras.
   - **Processing**: For each frame of the video stream, the system uses an object detection module (YOLO - You Only Look Once) to identify individuals.
   - **Default Boundary**: The system sets a default boundary for the detection zone if it has not been edited by the user.
   - **Counting**: The system counts the number of individuals within the designated zones for each frame.
   - **Output Stream**: The processed video stream, with the count overlay, is sent to the display page.

3. **Display Module**:
   - **Live Feed Count**: The count of individuals is displayed on the live video feed.
   - **Cumulative Count**: A cumulative count of all individuals detected by all cameras is also displayed.

4. **Editing Module**:
   - **Detection Zone Editing**: The user can add or edit the detection zones.
   - **Camera Editing**: The user can edit or delete cameras from the system.
   - **Configuration Check**: The system checks if the configurations are set up. If not, it loops back to allow further editing.

5. **Live Analytics**:
   - **Live Count Graph**: The system displays a live graph showing the count of individuals over time.
   - **Previous Counts**: It provides analytics such as previous day count, previous month count, and the average count.
   - **Max Count**: The system displays the maximum count attained during a specified period.
   - **Total Count**: A total count of individuals detected over time is presented.

The flowchart visually maps out the process flow and the interactions between various modules within a crowd counting application, which seems to include user account management, video processing for crowd counting, display of real-time data, editing tools for configurations, and live analytics for monitoring crowd sizes over different time frames.

## Performance and Output:
Performance comparison with other algorithms demonstrates YOLOv4's optimal speed and accuracy for real-time object detection. Output showcases the application's capabilities in both pre-recorded and live video scenarios, highlighting crowd counting, object detection, selective detection, and live analytics features. The application offers a user-friendly solution for crowd management and security enhancement.

## Conclusion:
The developed Real-time Crowd Counting application provides live analytics and selective detection features, addressing security concerns and aiding crowd management. With its ease of setup and usability in sparse crowd scenarios, the application offers practical solutions for infrastructure improvement and security enhancement. Future iterations aim to further enhance object detection capabilities using newer versions of the YOLO framework.

## What changed in version 2

Version 2 (2026) is a full rewrite. The ideas carried over: per-camera counting, "selective
detection" (now polygon zones), and live analytics.

| v1 (2021) | v2 |
|---|---|
| TensorFlow 2.3 RC, hand-ported YOLOv4, manual Darknet weight conversion | Ultralytics YOLO26 or RF-DETR, weights auto-download |
| Per-frame counts; boxes had to be fully inside a rectangle | ByteTrack IDs, unique-visitor counts, polygon zones on foot position |
| Flask + MongoDB, analytics never persisted | FastAPI + SQLAlchemy, per-minute history |
| Threads killed via `ctypes`, busy-wait loops | Cooperative stop events, condition variables |
| Werkzeug debugger exposed on LAN, hard-coded secret, unauthenticated GET-deletes | Auth on every route, ownership checks, httpOnly cookies |
| Hard-coded `http://<ip>:8080/video` (Android IP Webcam app), 720×480 | Any RTSP/RTMP/SRT/HLS/MJPEG/snapshot camera, ONVIF discovery, phone publishing without an app; resolution-independent zones |
| No tests, no CI | pytest + Vitest, ruff, ESLint, GitHub Actions, Docker |

Since then, v2 has also gained construction-site danger zones, an incident log, a no-login
public demo, and an AWS deployment. See the [documentation](README.md).

