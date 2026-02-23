import os
import sys
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import oracledb

# Initialize thick mode for older Oracle database compatibility
try:
    # Check if we're running in GitHub Actions (Linux environment)
    if 'GITHUB_ACTIONS' in os.environ:
        # GitHub Actions environment - try to use Oracle Instant Client
        oracle_lib_paths = [
            "/opt/oracle/instantclient_19_23",
            "/usr/lib/oracle/instantclient_19_23", 
            "/usr/local/oracle/instantclient_19_23"
        ]
        
        initialized = False
        for lib_path in oracle_lib_paths:
            if os.path.exists(lib_path):
                try:
                    oracledb.init_oracle_client(lib_dir=lib_path)
                    print(f"✅ Oracle thick mode initialized for GitHub Actions: {lib_path}")
                    initialized = True
                    break
                except Exception as e:
                    print(f"Failed to init with {lib_path}: {e}")
        
        if not initialized:
            print("⚠️  Oracle Instant Client not found, trying thin mode")
    else:
        # Local development environment
        oracledb.init_oracle_client()
        print("✅ Oracle thick mode initialized for local environment")
        
except Exception as e:
    print(f"⚠️  Warning: Could not initialize thick mode: {e}")
    print("Continuing with thin mode (may not work with older Oracle versions)")

# Load environment variables for local development only
if 'GITHUB_ACTIONS' not in os.environ:
    try:
        from dotenv import load_dotenv
        load_dotenv() 
        print("✅ Loaded .env file for local development")
    except ImportError:
        print("⚠️  python-dotenv not available, using system environment variables")


def set_output(name: str, value: str) -> None:
    """Set GitHub Actions output variables"""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def send_email_alert(metric_name: str, metric_value: int, threshold: int, utc_time: str) -> bool:
    """Send email alert when threshold is exceeded"""
    try:
        # Email configuration from environment variables
        smtp_server = os.environ["SMTP_SERVER"]
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ["SMTP_USER"]
        smtp_password = os.environ["SMTP_PASSWORD"]
        from_email = os.environ["FROM_EMAIL"]
        to_emails = os.environ["TO_EMAILS"].split(",")  # Comma-separated list
        
        # Create message
        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = f"ALERT: {metric_name} Threshold Exceeded"
        
        # Email body
        body = f"""
Alert: Message Count Threshold Exceeded

Metric: {metric_name}
Current Count: {metric_value}
Threshold: {threshold}
Time (UTC): {utc_time}

The number of messages with the specified status has exceeded the configured threshold.
Please investigate the L2 to MES message processing system.

This is an automated alert from the CheckMessagesFromL2ToMES monitoring script.
        """.strip()
        
        msg.attach(MIMEText(body, "plain"))
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        print(f"Email alert sent successfully to {', '.join(to_emails)}")
        return True
        
    except Exception as e:
        print(f"Failed to send email alert: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def main() -> int:
    """Main function to check database and send alerts"""
    # Database connection
    user = os.environ["ORACLE_USER"]
    password = os.environ["ORACLE_PASSWORD"]
    dsn = os.environ["ORACLE_DSN"]
    threshold = int(os.environ.get("THRESHOLD_VALUE", "100"))
    
    # Message monitoring configuration
    message_status = os.environ.get("MESSAGE_STATUS", "ERROR")  # Status to monitor
    table_name = os.environ.get("MESSAGE_TABLE", "L2_TO_MES_MESSAGES")  # Table name
    
    metric_name = f"L2_TO_MES_MESSAGES_STATUS_{message_status}_LAST_15_MIN"

    # SQL query to count messages with specific status in last 10 minutes
    sql = """
    select count(*) 
    from mes_send
    where status = 0
    and t_created > sysdate - (10/(24*60))
    """

    try:
        print(f"Environment: {'GitHub Actions' if 'GITHUB_ACTIONS' in os.environ else 'Local Development'}")
        print(f"Connecting to Oracle database: {dsn} as {user}")
        
        with oracledb.connect(user=user, password=password, dsn=dsn) as conn:
            print(f"✅ Connected successfully! Database version: {conn.version}")
            with conn.cursor() as cur:
                cur.execute(sql)
                result = cur.fetchone()
                metric_value = int(result[0] if result and result[0] else 0)

        utc_time = datetime.now(timezone.utc).isoformat()
        alert = metric_value >= threshold
        email_sent = False
        
        print(f"Messages currently on status 0: {metric_value}")
        print(f"Threshold: {threshold}")
        print(f"Alert triggered: {alert}")
        
        # Send email if threshold exceeded
        if alert:
            email_sent = send_email_alert(metric_name, metric_value, threshold, utc_time)
        else:
            print("No alert needed - message count is below threshold")

        # Set GitHub Actions outputs
        set_output("alert", "true" if alert else "false")
        set_output("metric_name", metric_name)
        set_output("metric_value", str(metric_value))
        set_output("threshold", str(threshold))
        set_output("utc_time", utc_time)
        set_output("email_sent", "true" if email_sent else "false")

        print(f"Final status: {metric_name}={metric_value}, threshold={threshold}, alert={alert}, email_sent={email_sent}")
        return 0

    except Exception as e:
        utc_time = datetime.now(timezone.utc).isoformat()
        
        # Set error outputs
        set_output("alert", "true")
        set_output("metric_name", "ORACLE_CHECK_FAILED")
        set_output("metric_value", "0")
        set_output("threshold", str(threshold))
        set_output("utc_time", utc_time)
        set_output("email_sent", "false")

        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        
        # Try to send error notification email
        try:
            send_email_alert("ORACLE_CHECK_FAILED", 0, threshold, utc_time)
        except:
            pass  # Don't fail if error email also fails
            
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
