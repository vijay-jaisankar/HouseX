import random
import os
import json
import numpy as np
from PIL import Image
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_recall_fscore_support, classification_report
from tqdm import tqdm, trange
import librosa
from librosa import display
import matplotlib.pyplot as plt

import torchvision
from torchvision import transforms, models
from torch.utils.tensorboard import SummaryWriter
import torch
from torch import nn, optim
from torch.utils.data import Dataset, DataLoader
import argparse
from datetime import date
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
from logger import log
import time 


DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

SEED = 0
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

EPOCHS = 20
LR = 2e-3
BATCH_SIZE = 4
data_path = "./"
song_types = ['future house', 'bass house', 'progressive house', 'melodic house']

def get_tensors(transform, path='./melspecgrams/', mode=None):
    # Collect data
    image_tensors = []
    label_tensors = []

    spec_dir = os.path.join(path, mode)
    img_list = [ele for ele in os.listdir(spec_dir) if '.jpg' in ele]
    for img in img_list:
        # song_type = img[:img.index('-')] # Expected file name example: bass house-1.jpg
        song_type = img.split('/')[-1].split("_")[0]
        # print(img, song_type)
        img_path = spec_dir + '/' + img
        img_tensor = transform(Image.open(img_path).convert('RGB'))
        image_tensors.append(img_tensor)
        label_tensors.append(song_types.index(song_type))

    return image_tensors, label_tensors


class MelSpectrogramDataset(Dataset):
    def __init__(self, images, labels):
        self.images = images
        self.labels = labels

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        # input, target
        return self.images[idx], torch.tensor(self.labels[idx], dtype=torch.long)


def one_epoch(model, loader, mode, device=DEVICE, epoch_id=None):
    def run(mode, device=device):
        criterion = nn.CrossEntropyLoss()
        losses = []
        correct_preds = 0
        length = 0
        for batch in tqdm(loader, desc='Epoch '+str(epoch_id+1)+' '+mode):
            images, labels = batch[0].to(device), batch[1].to(device)
            length += images.shape[0]

            outputs = model(images)
            preds = torch.argmax(outputs, dim=1)
            loss = criterion(outputs, labels)

            correct_preds += torch.sum(preds == labels).item()
            losses.append(loss.item())

            if mode == 'train':
                opt.zero_grad()
                loss.backward()
                opt.step()
        return {'loss': np.mean(losses), 'accuracy': correct_preds / length}

    if mode == 'train':
        opt = optim.SGD(model.parameters(), lr=LR)
        model = model.train()
        return run('train', device)
    else:
        model = model.eval()
        with torch.no_grad():
            return run('test', device)


def train(train_loader, val_loader, test_loader, model, epochs=EPOCHS, device=DEVICE, writer=None, eval_first=True):
    model = model.to(device)
    epoch = -1
    if eval_first:
        evaluate(model, device, val_loader, 'val', epoch)
        evaluate(model, device, test_loader, 'test', epoch)

    cur_log = log()
    for epoch in range(epochs):
        ret = one_epoch(model, train_loader, 'train', device, epoch)
        train_loss = ret['loss']
        train_acc = ret['accuracy']
        print('Epoch {}: '.format(epoch+1))
        print(f"train loss: {train_loss}")
        print(f"train accuracy: {train_acc}")

        val_loss, val_acc = evaluate(model, device, val_loader, 'val', epoch)
        test_loss, test_acc = evaluate(model, device, test_loader, 'test', epoch)
        if writer:
            writer.add_scalar('loss/train', train_loss, epoch)
            writer.add_scalar('accuracy/train', train_acc, epoch)
            writer.add_scalar('loss/val', val_loss, epoch)
            writer.add_scalar('accuracy/val', val_acc, epoch)
            writer.add_scalar('loss/test', test_loss, epoch)
            writer.add_scalar('accuracy/test', test_acc, epoch)
            
            cur_log.push(train_loss, train_acc, val_loss, val_acc, test_loss, test_acc)
    model = model.cpu()
    return cur_log


def evaluate(model, device=DEVICE, loader=None, comment='val', epoch_id=None):
    model = model.to(device)
    ret = one_epoch(model, loader, 'test', device, epoch_id)
    loss = ret['loss']
    accuracy = ret['accuracy']

    print(f"{comment} loss: {loss}")
    print(f"{comment} accuracy: {accuracy}")
    return loss, accuracy


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dropout', type=float, default=0.5)
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    parser.add_argument('--lr', type=float, default=LR)
    parser.add_argument('--id', type=int, default=-1)
    parser.add_argument('--metric', type=str, default='weighted')
    parser.add_argument('--pretrained', action='store_true', default=False)
    parser.add_argument('--do_train', action='store_true', default=False)
    parser.add_argument('--data_dir', type=str, default='./melspecgrams/')
    parser.add_argument('--batch_size', type=int, default=4)
    parser.add_argument('--network_version', type=str, default='legacy') # "legacy" or "experimental"
    parser.add_argument('--transforms_version', type=str, default='legacy') # "legacy" or "experimental"
    args = parser.parse_args()
    # Parse args
    print(args)
    print('Running on:', torch.cuda.get_device_name())
    LR, EPOCHS = args.lr, args.epochs
    BATCH_SIZE = args.batch_size
    DEVICE = torch.device('cuda:0' if args.id >= 0 else 'cpu')
    
    # Set backbone of the model
    backbone = None
    if args.id == 0:
        backbone = models.mobilenet_v3_small(pretrained=False)
        if args.pretrained:
            backbone = models.mobilenet_v3_small(weights="IMAGENET1K_V1")
    elif args.id == 1:
        backbone = models.resnet18(pretrained=False)
        if args.pretrained:
            backbone = models.resnet18(weights="IMAGENET1K_V1")
    elif args.id == 2:
        backbone = models.vgg16(pretrained=False)
        if args.pretrained:
            backbone = models.vgg16(weights="IMAGENET1K_V1")
    elif args.id == 3:
        backbone = models.densenet121(pretrained=False)
        if args.pretrained:
            backbone = models.densenet121(weights="IMAGENET1K_V1")
    elif args.id == 4:
        backbone = models.shufflenet_v2_x1_0(pretrained=False)
        if args.pretrained:
            backbone = models.shufflenet_v2_x1_0(weights="IMAGENET1K_V1")
    elif args.id == 5:
        from vit_pytorch import ViT
        backbone = ViT(
            image_size = 224,
            patch_size = 32,
            num_classes = 1000,
            dim = 512,
            depth = 6,
            heads = 16,
            mlp_dim = 512,
            dropout = 0.1,
            emb_dropout = 0.1
        )
    elif args.id == 6:
        backbone = models.vgg19(pretrained=False)
        if args.pretrained:
            backbone = models.vgg19(weights="IMAGENET1K_V1")
    elif args.id == 7:
        backbone = models.vgg19_bn(pretrained=False)
        if args.pretrained:
            backbone = models.vgg19_bn(weights="IMAGENET1K_V1")
    elif args.id == 8:
        backbone = models.resnet101(pretrained=False)
        if args.pretrained:
            backbone = models.resnet101(weights="IMAGENET1K_V1")
    elif args.id == 9:
        backbone = models.resnet50(pretrained=False)
        if args.pretrained:
            backbone = models.resnet50(weights="IMAGENET1K_V1")
    elif args.id == 10:
        backbone = models.squeezenet1_1(pretrained=False)
        if args.pretrained:
            backbone = models.squeezenet1_1(weights="IMAGENET1K_V1")
    elif args.id == 11:
        backbone = models.googlenet(pretrained=False)
        if args.pretrained:
            backbone = models.googlenet(weights="IMAGENET1K_V1")
    else:
        raise KeyError('Current backbone not supported...')

    print('backbone pretrained:', args.pretrained)

    # Construct the whole model on top of the backbone
    if args.id != 12:
        if args.network_version == "legacy":
            model = nn.Sequential(
                backbone,
                nn.Dropout(p=args.dropout),
                nn.Linear(1000, len(song_types))
            )
        else:
            model = nn.Sequential(
                backbone,
                nn.ReLU(),
                nn.BatchNorm1d(1000),
                nn.Dropout(p = args.dropout),
                nn.Linear(1000, len(song_types)),
            )

    # Construct the transforms for the dataset
    legacy_transform = transforms.Compose([
            transforms.Resize((96, 96)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
    
    if args.transforms_version == "legacy":
        train_transform = legacy_transform
    else:
        train_transform = transforms.Compose([
            transforms.Resize((96, 96)),
            transforms.RandomPosterize(2, p = 0.25),
            transforms.ColorJitter(brightness = (0.50, 1.00)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
    
    # Construct the train, test, and val loaders
    # @note We apply the legacy transforms for the test and validation datasets to aid in consistency of metrics' reporting 
    train_set = MelSpectrogramDataset(*get_tensors(train_transform, args.data_dir, mode='train'))
    val_set = MelSpectrogramDataset(*get_tensors(legacy_transform, args.data_dir, mode='val'))
    test_set = MelSpectrogramDataset(*get_tensors(legacy_transform, args.data_dir, mode='test'))

    train_loader = DataLoader(train_set, BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_set, BATCH_SIZE, shuffle=True)

    print('dataset length:', len(train_set), len(val_set), len(test_set))
    print('dataloader length:', len(train_loader), len(val_loader), len(test_loader))
    

    logdir = './logs/' + str(date.today()) + '_' + str(time.time()) + '_' + type(backbone).__name__ + "_LR_" + str(LR) + "EPOCH_" + str(EPOCHS)
    os.makedirs(logdir, exist_ok=True)
    if args.do_train:
        writer = SummaryWriter(log_dir=logdir)
        training_log = train(train_loader, val_loader, test_loader, model, EPOCHS, DEVICE, writer)
        training_log.save(os.path.join(logdir, 'training_log.json'))
        writer.close()
        torch.save(model, f'{logdir}/finetuned_{type(backbone).__name__}.pth')
    
    for mode in ['val', 'test']:
        print(f"{mode}:")
        model = torch.load(f'{logdir}/finetuned_{type(backbone).__name__}.pth')
        y_test, y_pred = [], []
        model = model.to(DEVICE)
        for images, labels in tqdm(test_loader if mode == 'test' else val_loader):
            images, labels = images.to(DEVICE), labels.to(DEVICE)
            outputs = model(images)
            preds = torch.argmax(outputs, dim=1)

            y_test += labels.cpu().numpy().tolist()
            y_pred += preds.cpu().numpy().tolist()

        model = model.cpu()

        cm = confusion_matrix(y_test, y_pred)
        _ = ConfusionMatrixDisplay(cm, display_labels=('FH', 'BH', 'PH', 'MH')).plot()
        plt.title(type(backbone).__name__)
        plt.savefig(f'./logs/{type(backbone).__name__} - confusion matrix on the {mode} set.png', bbox_inches='tight')
        plt.show()
        plt.close()
        report = classification_report(y_test, y_pred, target_names=song_types, output_dict=True)
        pretty_report = json.dumps(report, indent=4)
        print("precision/recall/f1-score/support:", pretty_report)
