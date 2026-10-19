import sys
import time
from pathlib import Path
sys.path.append(r"C:\dev\Anchor")
import pty_manager as pty

def main():
    try:
        sid = pty.start([r"C:\Users\example\AppData\Local\agy\bin\agy.exe", "-i", "Hello, please reply with 'xyz123'"], cwd=r"C:\dev\Anchor")
        print("Started:", sid)
        for i in range(10):
            time.sleep(1)
            out = pty.read_since(sid, 0)
            text = out.get("text", "")
            if "xyz123" in text.lower():
                print("Found response!")
                with open("test_agy_out.txt", "w", encoding="utf-8") as f:
                    f.write(text)
                break
        else:
            print("Timeout waiting for response.")
            out = pty.read_since(sid, 0)
            print(out.get("text", ""))
        pty.kill(sid)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
