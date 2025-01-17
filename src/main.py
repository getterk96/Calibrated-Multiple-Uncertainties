import argparse
import copy
import os
import random
import sys
import time

import numpy as np
import pandas as pd
import torch
import torch.backends.cudnn as cudnn
import torch.nn.functional as F
import torch.nn.parallel
import torch.utils.data
import torch.utils.data.distributed
import torchvision.transforms as transforms
from matplotlib import pyplot as plt
from sklearn.metrics import roc_auc_score, roc_curve
from torch.optim import SGD
from torch.utils.data import DataLoader

sys.path.append('.')
from model import DomainDiscriminator, Ensemble
from model import DomainAdversarialLoss, ImageClassifier, resnet50
import datasets
from datasets import esem_dataloader
from lib import AverageMeter, ProgressMeter, accuracy, ForeverDataIterator, AccuracyCounter, get_confidence
from lib import ResizeImage
from lib import StepwiseLR, get_entropy, get_marginal_confidence, norm

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

import warnings

warnings.simplefilter('ignore', UserWarning)


def main(args: argparse.Namespace):
    begin = time.time()
    if args.seed is not None:
        random.seed(args.seed)
        torch.manual_seed(args.seed)
        cudnn.deterministic = True

    cudnn.benchmark = True

    # Data loading code
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    train_transform = transforms.Compose([
        ResizeImage(256),
        transforms.RandomResizedCrop(224),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        normalize
    ])
    val_tranform = transforms.Compose([
        ResizeImage(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        normalize
    ])

    a, b, c = args.n_share, args.n_source_private, args.n_total
    common_classes = [i for i in range(a)]
    source_private_classes = [i + a for i in range(b)]
    target_private_classes = [i + a + b for i in range(c - a - b)]
    source_classes = common_classes + source_private_classes
    target_classes = common_classes + target_private_classes

    dataset = datasets.Office31
    train_source_dataset = dataset(root=args.root, data_list_file=args.source, filter_class=source_classes,
                                   transform=train_transform)
    train_source_loader = DataLoader(train_source_dataset, batch_size=args.batch_size,
                                     shuffle=True, num_workers=args.workers, drop_last=True)
    train_target_dataset = dataset(root=args.root, data_list_file=args.target, filter_class=target_classes,
                                   transform=train_transform)
    train_target_loader = DataLoader(train_target_dataset, batch_size=args.batch_size,
                                     shuffle=True, num_workers=args.workers, drop_last=True)
    val_dataset = dataset(root=args.root, data_list_file=args.target, filter_class=target_classes,
                          transform=val_tranform)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.workers)

    test_loader = val_loader

    train_source_iter = ForeverDataIterator(train_source_loader)
    train_target_iter = ForeverDataIterator(train_target_loader)

    # create model
    backbone = resnet50(pretrained=True)
    classifier = ImageClassifier(backbone, train_source_dataset.num_classes).to(device)
    domain_discri = DomainDiscriminator(in_feature=classifier.features_dim, hidden_size=1024).to(device)
    esem = Ensemble(classifier.features_dim, train_source_dataset.num_classes).to(device)
    # proto_cls = Cos_Classifier(classifier.features_dim, train_source_dataset.num_classes, scale=4).to(device)

    # define optimizer and lr scheduler
    optimizer = SGD(classifier.get_parameters() + domain_discri.get_parameters(),
                    args.lr, momentum=args.momentum, weight_decay=args.weight_decay, nesterov=True)
    lr_scheduler = StepwiseLR(optimizer, init_lr=args.lr, gamma=0.001, decay_rate=0.75)

    optimizer_esem = SGD(esem.get_parameters(), args.lr, momentum=args.momentum,
                         weight_decay=args.weight_decay, nesterov=True)
    lr_scheduler1 = StepwiseLR(optimizer_esem, init_lr=args.lr, gamma=0.001, decay_rate=0.75)
    lr_scheduler2 = StepwiseLR(optimizer_esem, init_lr=args.lr, gamma=0.001, decay_rate=0.75)
    lr_scheduler3 = StepwiseLR(optimizer_esem, init_lr=args.lr, gamma=0.001, decay_rate=0.75)
    lr_scheduler4 = StepwiseLR(optimizer_esem, init_lr=args.lr, gamma=0.001, decay_rate=0.75)
    lr_scheduler5 = StepwiseLR(optimizer_esem, init_lr=args.lr, gamma=0.001, decay_rate=0.75)

    optimizer_pre = SGD(esem.get_parameters() + classifier.get_parameters(), args.lr, momentum=args.momentum,
                        weight_decay=args.weight_decay, nesterov=True)
    lr_scheduler_pre = StepwiseLR(optimizer_pre, init_lr=args.lr, gamma=0.001, decay_rate=0.75)

    esem_iter1, esem_iter2, esem_iter3, esem_iter4, esem_iter5 = esem_dataloader(args, source_classes)

    # define loss function
    domain_adv = DomainAdversarialLoss(domain_discri, reduction='none').to(device)

    # _, ds, src = args.source.split('/')
    # _, _, tgt = args.target.split('/')
    #
    # if not os.path.exists(f"models/{ds}"):
    #     os.mkdir(f"models/{ds}")
    #
    # pretrain_model_path = f"models/{ds}/scw_{src[:-4]}_{tgt[:-4]}_pretrain.pth"
    # if not os.path.exists(pretrain_model_path):
    #     for epoch in range(args.pre_epochs):
    #         pretrain(train_source_iter, esem_iter1, esem_iter2, esem_iter3, esem_iter4, esem_iter5, classifier,
    #                  esem, optimizer_pre, args, epoch, lr_scheduler_pre)
    #
    #         evaluate_source_common(val_loader, classifier, esem, source_classes, args)
    #         auc = plot_roc(val_loader, classifier, esem, source_classes, args)
    #         print(f"Got AUC {auc:.4f}")
    #
    #     state = {'classifier': classifier.state_dict(), 'esem': esem.state_dict()}
    #
    #     torch.save(state, pretrain_model_path)
    # else:
    #     checkpoint = torch.load(pretrain_model_path)
    #
    #     classifier.load_state_dict(checkpoint['classifier'])
    #     esem.load_state_dict(checkpoint['esem'])
    #
    #     plot_pr(val_loader, classifier, esem, source_classes, args)

    target_score_upper = torch.zeros(1).to(device)
    target_score_lower = torch.zeros(1).to(device)
    source_class_weight = torch.ones(len(source_classes))
    print(source_class_weight)

    # start training
    best_acc1 = 0.
    for epoch in range(args.epochs):
        # train for one epoch
        target_score_upper, target_score_lower = train(train_source_iter, train_target_iter, classifier, domain_adv,
                                                       esem, optimizer, lr_scheduler, epoch, source_class_weight,
                                                       target_score_upper, target_score_lower, args)

        train_esem(esem_iter1, classifier, esem, optimizer_esem, lr_scheduler1, epoch, args, index=1)
        train_esem(esem_iter2, classifier, esem, optimizer_esem, lr_scheduler2, epoch, args, index=2)
        train_esem(esem_iter3, classifier, esem, optimizer_esem, lr_scheduler3, epoch, args, index=3)
        train_esem(esem_iter4, classifier, esem, optimizer_esem, lr_scheduler4, epoch, args, index=4)
        train_esem(esem_iter5, classifier, esem, optimizer_esem, lr_scheduler5, epoch, args, index=5)

        source_class_weight = evaluate_source_common(val_loader, classifier, esem, source_classes, args)
        mask = torch.where(source_class_weight > 0.1)
        source_class_weight = torch.zeros_like(source_class_weight)
        source_class_weight[mask] = 1
        print(source_class_weight)

        # evaluate on validation set
        acc1 = validate(val_loader, classifier, esem, source_classes, args)

        # remember best acc@1 and save checkpoint
        if acc1 > best_acc1:
            best_model = copy.deepcopy(classifier.state_dict())
        best_acc1 = max(acc1, best_acc1)

    print("best_acc1 = {:3.3f}".format(best_acc1))

    # evaluate on test set
    classifier.load_state_dict(best_model)
    acc1 = validate(test_loader, classifier, esem, source_classes, args)
    print("test_acc1 = {:3.3f}".format(acc1))
    end = time.time()
    print(f"Total experiment time: {(end - begin) // 60}min")


def pretrain(train_source_iter: ForeverDataIterator, esem_iter1, esem_iter2, esem_iter3, esem_iter4, esem_iter5, model,
             esem, optimizer, args, epoch, lr_scheduler):
    losses = AverageMeter('Loss', ':6.2f')
    cls_accs = AverageMeter('Cls Acc', ':3.1f')
    progress = ProgressMeter(
        args.iters_per_epoch,
        [losses, cls_accs],
        prefix="Pre: [{}]".format(epoch))

    model.train()
    esem.train()

    for i in range(args.iters_per_epoch):
        lr_scheduler.step()

        x_s, labels_s = next(train_source_iter)
        x_s = x_s.to(device)
        labels_s = labels_s.to(device)
        y_s, f_s = model(x_s)
        cls_loss = F.cross_entropy(y_s, labels_s)

        x_s1, labels_s1 = next(esem_iter1)
        x_s1 = x_s1.to(device)
        labels_s1 = labels_s1.to(device)
        y_s1, f_s1 = model(x_s1)
        y_s1 = esem(f_s1, index=1)
        loss1 = F.cross_entropy(y_s1, labels_s1)

        x_s2, labels_s2 = next(esem_iter2)
        x_s2 = x_s2.to(device)
        labels_s2 = labels_s2.to(device)
        y_s2, f_s2 = model(x_s2)
        y_s2 = esem(f_s2, index=2)
        loss2 = F.cross_entropy(y_s2, labels_s2)

        x_s3, labels_s3 = next(esem_iter3)
        x_s3 = x_s3.to(device)
        labels_s3 = labels_s3.to(device)
        y_s3, f_s3 = model(x_s3)
        y_s3 = esem(f_s3, index=3)
        loss3 = F.cross_entropy(y_s3, labels_s3)

        x_s4, labels_s4 = next(esem_iter4)
        x_s4 = x_s4.to(device)
        labels_s4 = labels_s4.to(device)
        y_s4, f_s4 = model(x_s4)
        y_s4 = esem(f_s4, index=4)
        loss4 = F.cross_entropy(y_s4, labels_s4)

        x_s5, labels_s5 = next(esem_iter5)
        x_s5 = x_s5.to(device)
        labels_s5 = labels_s5.to(device)
        y_s5, f_s5 = model(x_s5)
        y_s5 = esem(f_s5, index=5)
        loss5 = F.cross_entropy(y_s5, labels_s5)

        cls_acc = accuracy(y_s1, labels_s1)[0]
        cls_accs.update(cls_acc.item(), x_s1.size(0))

        loss = loss1 + loss2 + loss3 + loss4 + loss5 + cls_loss
        losses.update(loss.item(), x_s1.size(0))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if i % (args.print_freq) == 0:
            progress.display(i)


def train(train_source_iter: ForeverDataIterator, train_target_iter: ForeverDataIterator,
          model: ImageClassifier, domain_adv: DomainAdversarialLoss, esem, optimizer: SGD,
          lr_scheduler: StepwiseLR, epoch: int, source_class_weight, target_score_upper, target_score_lower,
          args: argparse.Namespace):
    batch_time = AverageMeter('Time', ':4.2f')
    losses = AverageMeter('Loss', ':4.2f')
    cls_accs = AverageMeter('Cls Acc', ':4.1f')
    domain_accs = AverageMeter('Domain Acc', ':4.1f')
    score_upper = AverageMeter('Score Upper', ':4.2f')
    score_lower = AverageMeter('Score Lower', ':4.2f')
    progress = ProgressMeter(
        args.iters_per_epoch,
        [batch_time, losses, cls_accs, domain_accs, score_upper, score_lower],
        prefix="Epoch: [{}]".format(epoch))

    # switch to train mode
    model.train()
    domain_adv.train()
    esem.eval()

    end = time.time()
    for i in range(args.iters_per_epoch):
        lr_scheduler.step()

        x_s, labels_s = next(train_source_iter)
        x_t, _ = next(train_target_iter)

        x_s = x_s.to(device)
        x_t = x_t.to(device)
        labels_s = labels_s.to(device)

        # compute output
        y_s, f_s = model(x_s)
        y_t, f_t = model(x_t)

        with torch.no_grad():
            yt_1, yt_2, yt_3, yt_4, yt_5 = esem(f_t)
            confidence = get_marginal_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            entropy = get_entropy(yt_1, yt_2, yt_3, yt_4, yt_5)
            w_t = (1 - entropy + confidence) / 2
            target_score_upper = target_score_upper * 0.01 + w_t.max() * 0.99
            target_score_lower = target_score_lower * 0.01 + w_t.min() * 0.99
            w_t = (w_t - target_score_lower) / (target_score_upper - target_score_lower)
            w_s = torch.tensor([source_class_weight[i] for i in labels_s]).to(device)

        cls_loss = F.cross_entropy(y_s, labels_s)
        transfer_loss = domain_adv(f_s, f_t, w_s.detach(), w_t.to(device).detach())
        domain_acc = domain_adv.domain_discriminator_accuracy
        loss = cls_loss + transfer_loss * args.trade_off

        cls_acc = accuracy(y_s, labels_s)[0]

        losses.update(loss.item(), x_s.size(0))
        cls_accs.update(cls_acc.item(), x_s.size(0))
        domain_accs.update(domain_acc.item(), x_s.size(0))
        score_upper.update(target_score_upper.item(), 1)
        score_lower.update(target_score_lower.item(), 1)

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            progress.display(i)

    return target_score_upper, target_score_lower


def train_esem(train_source_iter, model, esem, optimizer, lr_scheduler, epoch, args, index):
    losses = AverageMeter('Loss', ':4.2f')
    cls_accs = AverageMeter('Cls Acc', ':5.1f')
    progress = ProgressMeter(
        args.iters_per_epoch // 2,
        [losses, cls_accs],
        prefix="Esem: [{}-{}]".format(epoch, index))

    model.eval()
    esem.train()

    for i in range(args.iters_per_epoch // 2):
        lr_scheduler.step()

        x_s, labels_s = next(train_source_iter)
        x_s = x_s.to(device)
        labels_s = labels_s.to(device)

        # compute output
        with torch.no_grad():
            y_s, f_s = model(x_s)
        y_s = esem(f_s.detach(), index)

        loss = F.cross_entropy(y_s, labels_s)
        cls_acc = accuracy(y_s, labels_s)[0]

        losses.update(loss.item(), x_s.size(0))
        cls_accs.update(cls_acc.item(), x_s.size(0))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if i % args.print_freq == 0:
            progress.display(i)


def validate(val_loader: DataLoader, model: ImageClassifier, esem, source_classes: list,
             args: argparse.Namespace) -> float:
    # switch to evaluate mode
    model.eval()
    esem.eval()

    all_confidence = list()
    all_entropy = list()
    all_indices = list()
    all_labels = list()

    with torch.no_grad():
        for i, (images, labels) in enumerate(val_loader):
            images = images.to(device)
            labels = labels.to(device)

            output, f = model(images)
            values, indices = torch.max(F.softmax(output, -1), 1)

            yt_1, yt_2, yt_3, yt_4, yt_5 = esem(f)
            confidence = get_marginal_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            entropy = get_entropy(yt_1, yt_2, yt_3, yt_4, yt_5)

            all_confidence.extend(confidence)
            all_entropy.extend(entropy)
            all_indices.extend(indices)
            all_labels.extend(labels)

    all_confidence = norm(torch.tensor(all_confidence))
    all_entropy = norm(torch.tensor(all_entropy))
    all_score = (all_confidence + 1 - all_entropy) / 2

    counters = AccuracyCounter(len(source_classes) + 1)
    for (each_indice, each_label, score) in zip(all_indices, all_labels, all_score):
        if each_label in source_classes:
            counters.add_total(each_label)
            if score >= args.threshold and each_indice == each_label:
                counters.add_correct(each_label)
        else:
            counters.add_total(-1)
            if score < args.threshold:
                counters.add_correct(-1)

    print('---counters---')
    print(counters.each_accuracy())
    print(counters.mean_accuracy())
    print(counters.h_score())

    return counters.mean_accuracy()


def plot_roc(val_loader: DataLoader, model: ImageClassifier, esem, source_classes: list, args: argparse.Namespace):
    # switch to evaluate mode
    model.eval()
    esem.eval()

    all_confidence = list()
    all_marginal_confidence = list()
    all_entropy = list()
    all_labels = list()

    with torch.no_grad():
        for i, (images, labels) in enumerate(val_loader):
            images = images.to(device)

            _, f = model(images)
            yt_1, yt_2, yt_3, yt_4, yt_5 = esem(f)
            confidence = get_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            marginal_confidence = get_marginal_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            entropy = get_entropy(yt_1, yt_2, yt_3, yt_4, yt_5)

            all_confidence.extend(confidence)
            all_marginal_confidence.extend(marginal_confidence)
            all_entropy.extend(entropy)
            all_labels.extend(labels)

    all_confidence = norm(torch.tensor(all_confidence))
    all_marginal_confidence = norm(torch.tensor(all_marginal_confidence))
    all_entropy = norm(torch.tensor(all_entropy))
    all_score_a = (all_confidence)
    all_score_b = (all_marginal_confidence)
    all_score_c = (1 - all_entropy)

    common_labels = []
    for i in range(len(all_labels)):
        common_labels.append(1 if all_labels[i] in source_classes else 0)

    all_score_a = all_score_a.numpy()
    all_score_b = all_score_b.numpy()
    all_score_c = all_score_c.numpy()
    common_labels = np.array(common_labels)

    fpr_a, tpr_a, _ = roc_curve(common_labels, all_score_a)
    fpr_b, tpr_b, _ = roc_curve(common_labels, all_score_b)
    fpr_c, tpr_c, _ = roc_curve(common_labels, all_score_c)
    roc_auc_a = roc_auc_score(common_labels, all_score_a)
    roc_auc_b = roc_auc_score(common_labels, all_score_b)
    roc_auc_c = roc_auc_score(common_labels, all_score_c)

    source = args.source.split("/")[-1][:-4].capitalize()
    target = args.target.split("/")[-1][:-4].capitalize()
    plt.figure(1)
    plt.plot([0, 1], [0, 1], 'm,-')
    plt.plot(fpr_a, tpr_a, label=f'AUC Conf={roc_auc_a: .3f}')
    plt.plot(fpr_b, tpr_b, label=f'AUC Margin={roc_auc_b: .3f}')
    plt.plot(fpr_c, tpr_c, label=f'AUC Ent={roc_auc_c: .3f}')
    plt.xlabel('FPR')
    plt.ylabel('TPR')
    plt.title(f'{source}->{target} ROC')
    plt.legend(loc='best')
    plt.savefig(f'ablation/{source}->{target}.png')


def cal_pr(scores, labels, thresholds):
    new_scores = zip(scores.numpy(), labels)
    new_scores = np.array(sorted(new_scores, key=lambda x: x[0], reverse=True))

    points = []
    for threshold in thresholds:
        TP, FP, FN = 0, 0, 0
        for score, label in new_scores:
            if score >= threshold:
                if label:
                    TP += 1
                else:
                    FP += 1
            else:
                if label:
                    FN += 1
        points.append([TP / (TP + FN + 1e-7), TP / (TP + FP + 1e-7)])

    print_points = [[0., 1.]] + sorted(points, key=lambda x: x[0]) + [[1., 0.]]
    return list(zip(*print_points)), points


def plot_pr(val_loader: DataLoader, model: ImageClassifier, esem, source_classes: list, args: argparse.Namespace):
    # switch to evaluate mode
    model.eval()
    esem.eval()

    all_confidence = list()
    all_marginal_confidence = list()
    all_entropy = list()
    all_labels = list()

    with torch.no_grad():
        for i, (images, labels) in enumerate(val_loader):
            images = images.to(device)

            _, f = model(images)
            yt_1, yt_2, yt_3, yt_4, yt_5 = esem(f)
            confidence = get_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            marginal_confidence = get_marginal_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            entropy = get_entropy(yt_1, yt_2, yt_3, yt_4, yt_5)

            all_confidence.extend(confidence)
            all_marginal_confidence.extend(marginal_confidence)
            all_entropy.extend(entropy)
            all_labels.extend(labels)

    all_confidence = norm(torch.tensor(all_confidence))
    all_marginal_confidence = norm(torch.tensor(all_marginal_confidence))
    all_entropy = norm(torch.tensor(all_entropy))
    all_scores = [all_confidence, all_marginal_confidence, 1 - all_entropy,
                  (all_confidence + 1 - all_entropy) / 2,
                  (all_marginal_confidence + 1 - all_entropy) / 2,
                  (all_confidence + all_marginal_confidence) / 2,
                  (all_confidence + all_marginal_confidence + 1 - all_entropy) / 3]

    common_labels = [(1 if label in source_classes else 0) for label in all_labels]
    common_labels = np.array(common_labels)

    step = 0.05
    source = args.source.split("/")[-1][:-4].capitalize()
    target = args.target.split("/")[-1][:-4].capitalize()
    names = ['Conf', 'Margin', 'Entropy', 'Conf+Entropy', 'Margin+Entropy', 'Conf+Margin', 'Conf+Margin+Entropy']
    thresholds = [thresh * step for thresh in range(int(1 / step) - 1, -1, -1)]

    plt.figure(1)
    plt.plot([0, 1], [0, 1], 'm,-')
    results = []
    for i, scores in enumerate(all_scores):
        results.append([])
        (recall, precision), points = cal_pr(scores, common_labels, thresholds)
        plt.plot(recall, precision, label=names[i])
        for j, point in enumerate(points):
            recall, precision = point
            results[-1].append((2 * recall * precision) / (recall + precision))
    columns = []
    for threshold in thresholds:
        columns.append(f"T{threshold:.2f}")
    pd.DataFrame(results, index=names, columns=columns).to_excel(f"ablation/F1-{source}->{target}.xlsx")
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title(f'{source}->{target} PR')
    plt.legend(loc='best')
    plt.savefig(f'ablation/PR-{source}->{target}.png')


def evaluate_source_common(val_loader: DataLoader, model: ImageClassifier, esem, source_classes: list,
                           args: argparse.Namespace):
    temperature = 1
    # switch to evaluate mode
    model.eval()
    esem.eval()

    common = []
    target_private = []

    all_confidence = list()
    all_entropy = list()
    all_labels = list()
    all_output = list()

    source_weight = torch.zeros(len(source_classes)).to(device)
    cnt = 0
    with torch.no_grad():
        for i, (images, labels) in enumerate(val_loader):
            images = images.to(device)

            output, f = model(images)
            output = F.softmax(output, -1) / temperature
            yt_1, yt_2, yt_3, yt_4, yt_5 = esem(f)
            confidence = get_marginal_confidence(yt_1, yt_2, yt_3, yt_4, yt_5)
            entropy = get_entropy(yt_1, yt_2, yt_3, yt_4, yt_5)

            all_confidence.extend(confidence)
            all_entropy.extend(entropy)
            all_labels.extend(labels)

            for each_output in output:
                all_output.append(each_output)

    all_confidence = norm(torch.tensor(all_confidence))
    all_entropy = norm(torch.tensor(all_entropy))
    all_score = (all_confidence + 1 - all_entropy) / 2

    print('source_threshold = {}'.format(args.source_threshold))

    for i in range(len(all_score)):
        if all_score[i] >= args.source_threshold:
            source_weight += all_output[i]
            cnt += 1
        if all_labels[i] in source_classes:
            common.append(all_score[i])
        else:
            target_private.append(all_score[i])

    hist, bin_edges = np.histogram(common, bins=20, range=(0, 1))
    print(hist)

    hist, bin_edges = np.histogram(target_private, bins=20, range=(0, 1))
    print(hist)

    source_weight = norm(source_weight / cnt)
    print('---source_weight---')
    print(source_weight)
    return source_weight


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PyTorch Domain Adaptation')
    parser.add_argument('root', help='root path of dataset')
    parser.add_argument('-d', '--data', default='Office31', help='dataset selected')
    parser.add_argument('-s', '--source', help='source domain(s)')
    parser.add_argument('-t', '--target', help='target domain(s)')
    parser.add_argument('-a', '--arch', default='resnet50', help='backbone selected')
    parser.add_argument('-j', '--workers', default=4, type=int, help='number of data loading workers (default: 4)')
    parser.add_argument('--pre_epochs', default=2, type=int, help='number of pretrain epochs to run')
    parser.add_argument('--epochs', default=20, type=int, help='number of total epochs to run')
    parser.add_argument('-b', '--batch_size', default=32, type=int, help='mini-batch size (default: 32)')
    parser.add_argument('--lr', '--learning_rate', default=0.01, type=float, help='initial learning rate', dest='lr')
    parser.add_argument('--momentum', default=0.9, type=float, help='momentum')
    parser.add_argument('--wd', '--weight_decay', default=1e-3, type=float, help='weight decay (default: 1e-3)',
                        dest='weight_decay')
    parser.add_argument('-p', '--print_freq', default=100, type=int, help='print frequency (default: 100)')
    parser.add_argument('--seed', default=None, type=int, help='seed for initializing training. ')
    parser.add_argument('--trade_off', default=1., type=float, help='the trade-off hyper-parameter for transfer loss')
    parser.add_argument('-i', '--iters_per_epoch', default=1000, type=int, help='Number of iterations per epoch')
    parser.add_argument('--n_share', default=10, type=int, help=" ")
    parser.add_argument('--n_source_private', default=10, type=int, help=" ")
    parser.add_argument('--n_total', default=31, type=int, help=" ")
    parser.add_argument('--threshold', default=0.6, type=float, help=" ")
    parser.add_argument('--source_threshold', default=0.9, type=float, help=" ")
    args = parser.parse_args()
    print(args)
    main(args)
