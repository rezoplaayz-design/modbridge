ModBridge Cloud Ready v9

TRUE 24/7 FREE RECOMMENDATION
-----------------------------
Oracle Cloud Always Free VM is the best fit for this app because it runs a real
Python backend and creates temporary/generated files.

The server now:
- listens on 0.0.0.0 instead of only 127.0.0.1
- supports HOST and PORT environment variables
- does not try to open a browser on a cloud server
- includes deploy_oracle.sh for systemd auto-start after reboot

QUICK ORACLE UBUNTU DEPLOY
--------------------------
1. Create an Ubuntu Always Free VM.
2. Upload this folder to the VM.
3. SSH into the VM.
4. Run:
   chmod +x start.sh deploy_oracle.sh
   ./deploy_oracle.sh
5. In Oracle Cloud networking, allow inbound TCP port 8765.
6. Open:
   http://YOUR_PUBLIC_IP:8765/

LOCAL WINDOWS
-------------
Double-click run.bat.

IMPORTANT
---------
The runtime/ folder stores uploaded/generated jobs. On a VPS this stays on disk
until you delete it. Add cleanup/quotas before opening the service to lots of users.
