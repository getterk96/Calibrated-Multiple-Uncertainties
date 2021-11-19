import argparse
import os
import random

parser = argparse.ArgumentParser(description='PyTorch Domain Adaptation')
parser.add_argument('--dir', "-d", type=str, default="data/office")
parser.add_argument('--min_img_num', "-m", type=int, default=5)
args = parser.parse_args()

for idx_file in os.listdir(args.dir):
    full_path = os.path.join(args.dir, idx_file)
    with open(full_path, "r") as f:
        lines = f.readlines()
        all_data = {}
        for line in lines:
            img_path, cls = line.strip().split()
            if cls not in all_data:
                all_data[cls] = []
            all_data[cls].append(img_path)
        all_data = list(all_data.items())
        all_data = sorted(all_data, key=lambda x: len(x[1]), reverse=True)
        cur_max = len(all_data[0][1])
        cur_min = args.min_img_num
        new_data = []
        for i, item in enumerate(all_data):
            tgt_num = round((cur_max - cur_min) / ((i + 1) ** 2)) + cur_min
            temp = item[1]
            random.shuffle(temp)
            new_data.append([item[0], temp[:tgt_num]])
        new_data = sorted(new_data, key=lambda x: x[0])

        out_dir = args.dir + "-lt"
        if not os.path.exists(out_dir):
            os.mkdir(out_dir)
        full_out_path = os.path.join(out_dir, idx_file)

        with open(full_out_path, "w") as out_f:
            for item in new_data:
                for pic in item[1]:
                    out_f.write(f"{pic} {item[0]}\n")

