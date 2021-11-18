CUDA_VISIBLE_DEVICES=0 python3 new/main.py /data/office -d Office31 -s data/office/amazon.txt -t data/office/webcam.txt --n_share 10 --n_source_private 10 --n_total 31 --epochs 20 --threshold 0.6 --seed 2021 | tee "logs/aw_0.6.log"

CUDA_VISIBLE_DEVICES=0 python3 new/main.py /data/office -d Office31 -s data/office/webcam.txt -t data/office/amazon.txt --n_share 10 --n_source_private 10 --n_total 31 --epochs 20 --threshold 0.6 --seed 2021 | tee "logs/wa_0.6.log"
