import re

class LogParser:

    def parse(self, filepath):
        parsed_logs = []

        with open(filepath, "r") as f:
            for line in f:
                match = re.match(
                    r"\[(.*?)\]\s(\w+)\s(.*)",
                    line.strip()
                )

                if match:
                    parsed_logs.append({
                        "timestamp": match.group(1),
                        "level": match.group(2),
                        "message": match.group(3)
                    })

        return parsed_logs


if __name__ == "__main__":
    parser = LogParser()
    logs = parser.parse("data/sample_logs.log")

    for log in logs:
        print(log)
