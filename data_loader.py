import glob
from tqdm import tqdm

import torch
from torch.utils.data import Dataset, DataLoader, TensorDataset

import os
import numpy as np
import sklearn.model_selection
from scipy.io.arff import loadarff

class LibsvmDataset(Dataset):
    """ Dataset loader for Libsvm data format """
    def __init__(self, fname, nfields):

        def decode_libsvm(line):
            columns = line.split(' ')
            map_func = lambda pair: (int(pair[0]), float(pair[1]))
            id, value = zip(*map(lambda col: map_func(col.split(':')), columns[1:]))
            sample = {'id': torch.LongTensor(id),
                      'value': torch.FloatTensor(value),
                      'y': float(columns[0])}
            return sample

        with open(fname) as f:
            sample_lines = sum(1 for line in f)

        self.feat_id = torch.LongTensor(sample_lines, nfields)
        self.feat_value = torch.FloatTensor(sample_lines, nfields)
        self.y = torch.FloatTensor(sample_lines)

        self.nsamples = 0
        with tqdm(total=sample_lines) as pbar:
            with open(fname) as fp:
                line = fp.readline()
                while line:
                    try:
                        sample = decode_libsvm(line)
                        self.feat_id[self.nsamples] = sample['id']
                        self.feat_value[self.nsamples] = sample['value']
                        self.y[self.nsamples] = sample['y']
                        self.nsamples += 1
                    except Exception:
                        print(f'incorrect data format line "{line}" !')
                    line = fp.readline()
                    pbar.update(1)
        print(f'# {self.nsamples} data samples loaded...')

    def __len__(self):
        return self.nsamples

    def __getitem__(self, idx):
        return {'id': self.feat_id[idx],
                'value': self.feat_value[idx],
                'y': self.y[idx]}

def libsvm_dataloader(args):
    data_dir = args.data_dir + args.dataset
    train_file = glob.glob("%s/tr*libsvm" % data_dir)[0]
    val_file = glob.glob("%s/va*libsvm" % data_dir)[0]
    test_file = glob.glob("%s/te*libsvm" % data_dir)[0]

    train_loader = DataLoader(LibsvmDataset(train_file, args.nfield),
                              batch_size=args.batch_size, shuffle=True,
                              num_workers=args.workers, pin_memory=True)
    val_loader = DataLoader(LibsvmDataset(val_file, args.nfield),
                            batch_size=args.batch_size, shuffle=False,
                            num_workers=args.workers, pin_memory=True)
    test_loader = DataLoader(LibsvmDataset(test_file, args.nfield),
                            batch_size=args.batch_size, shuffle=False,
                            num_workers=args.workers, pin_memory=True)

    return train_loader, val_loader, test_loader


class UCILibsvmDataset(Dataset):
    """ Dataset loader for loading UCI dataset of Libsvm format """
    def __init__(self, X, y):
        assert X.shape[0] == y.shape[0]
        self.nsamples, self.nfeat = X.shape

        self.feat_id = torch.LongTensor(self.nsamples, self.nfeat)
        self.feat_value = torch.FloatTensor(self.nsamples, self.nfeat)
        self.y = torch.FloatTensor(self.nsamples)

        with tqdm(total=self.nsamples) as pbar:
            id = torch.LongTensor(range(self.nfeat))
            for idx in range(self.nsamples):
                self.feat_id[idx] = id
                self.feat_value[idx] = torch.FloatTensor(X[idx])
                self.y[idx] = y[idx]

                pbar.update(1)
        print(f'Data loader: {self.nsamples} data samples')

    def __len__(self):
        return self.nsamples

    def __getitem__(self, idx):
        return {'id': self.feat_id[idx],
                'value': self.feat_value[idx],
                'y': self.y[idx]}

def uci_loader(data_dir, batch_size, valid_perc=0., libsvm=False, workers=4):
    '''
    :param data_dir:        Path to load the uci dataset
    :param batch_size:      Batch size
    :param valid_perc:      valid percentage split from train (default 0, whole train set)
    :param libsvm:          Libsvm loader of format {'id', 'value', 'y'}
    :param workers:         the number of subprocesses to load data
    :return:                train/valid/test loader, train_loader.nclass
    '''

    def uci_validation_set(X, y, split_perc=0.2):
        return sklearn.model_selection.train_test_split(
            X, y, test_size=split_perc, random_state=0)

    def make_loader(X, y, transformer=None, batch_size=64):
        if transformer is None:
            transformer = sklearn.preprocessing.StandardScaler()
            transformer.fit(X)
        X = transformer.transform(X)
        if libsvm:
            return DataLoader(UCILibsvmDataset(X, y),
                              batch_size=batch_size,
                              shuffle=transformer is None,
                              num_workers=workers, pin_memory=True
                              ), transformer
        else:
            return DataLoader(
                dataset=TensorDataset(*[torch.from_numpy(e) for e in [X, y]]),
                batch_size=batch_size,
                shuffle=transformer is None,
                num_workers=workers, pin_memory=True
            ), transformer

    def uci_folder_to_name(f):
        return f.split('/')[-1]

    def line_to_idx(l):
        return np.array([int(e) for e in l.split()], dtype=np.int32)

    def load_uci_dataset(folder, train=True):
        full_file = f'{folder}/{uci_folder_to_name(folder)}.arff'
        if os.path.exists(full_file):
            data = loadarff(full_file)
            train_idx, test_idx = [line_to_idx(l) for l in open(f'{folder}/conxuntos.dat').readlines()]
            assert len(set(train_idx) & set(test_idx)) == 0
            all_idx = list(train_idx) + list(test_idx)
            assert len(all_idx) == np.max(all_idx) + 1
            assert np.min(all_idx) == 0
            if train:
                data = (data[0][train_idx], data[1])
            else:
                data = (data[0][test_idx], data[1])
        else:
            typename = 'train' if train else 'test'
            filename = f'{folder}/{uci_folder_to_name(folder)}_{typename}.arff'
            data = loadarff(filename)
        assert data[1].types() == ['numeric'] * (len(data[1].types()) - 1) + ['nominal']
        X = np.array(data[0][data[1].names()[:-1]].tolist())
        y = np.array([int(e) for e in data[0][data[1].names()[-1]]])
        nclass = len(data[1]['clase'][1])
        return X.astype(np.float32), y, nclass

    Xtrain, ytrain, nclass = load_uci_dataset(data_dir)
    if valid_perc > 0:
        Xtrain, Xvalid, ytrain, yvalid = uci_validation_set(Xtrain, ytrain, split_perc=valid_perc)
        train_loader, _ = make_loader(Xtrain, ytrain, batch_size=batch_size)
        valid_loader, _ = make_loader(Xvalid, yvalid, batch_size=batch_size)
    else:
        train_loader, _ = make_loader(Xtrain, ytrain, batch_size=batch_size)
        valid_loader = train_loader

    print(f'{uci_folder_to_name(data_dir)}: {len(ytrain)} training samples loaded.')
    Xtest, ytest, _ = load_uci_dataset(data_dir, False)
    test_loader, _ = make_loader(Xtest, ytest, batch_size=batch_size)
    print(f'{uci_folder_to_name(data_dir)}: {len(ytest)} testing samples loaded.')
    train_loader.nclass = nclass
    return train_loader, valid_loader, test_loader