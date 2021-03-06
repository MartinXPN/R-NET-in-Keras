# from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import json
import os
from os import path

import numpy as np
from gensim.models import KeyedVectors
from gensim.scripts.glove2word2vec import glove2word2vec
from keras.preprocessing.sequence import pad_sequences
from stanford_corenlp_pywrapper.sockwrap import CoreNLP
from tqdm import tqdm
from unidecode import unidecode

from utils import CoreNLP_path, get_glove_file_path, get_fasttext_model_path, FastText

try:
    import cPickle as pickle
except ImportError:
    import _pickle as pickle


def CoreNLP_tokenizer():
    proc = CoreNLP(configdict={'annotators': 'tokenize,ssplit'},
                   corenlp_jars=[path.join(CoreNLP_path(), '*')])

    def tokenize_context(context):
        parsed = proc.parse_doc(context)
        tokens = []
        char_offsets = []
        for sentence in parsed['sentences']:
            tokens += sentence['tokens']
            char_offsets += sentence['char_offsets']

        return tokens, char_offsets

    return tokenize_context


def initialize_fasttext(fasttext_lib_path, fasttext_model_path):

    fasttext_model_path = get_fasttext_model_path(fasttext_model_path)
    print('Loading fasttext model...')
    model = FastText(fasttext_lib_directory=fasttext_lib_path, fasttext_model_path=fasttext_model_path)

    def get_word_vector(word):
        try:
            return model[word]
        except KeyError as e:
            # print(e)
            return np.zeros(model.vector_size)

    return get_word_vector


def word2vec(word2vec_path):
    # Download word2vec data if it's not present yet
    if not path.exists(word2vec_path):
        glove_file_path = get_glove_file_path()
        print('Converting Glove to word2vec...', end='')
        glove2word2vec(glove_file_path, word2vec_path)  # Convert glove to word2vec
        os.remove(glove_file_path)                      # Remove glove file and keep only word2vec
        print('Done')

    print('Reading word2vec data... ', end='')
    model = KeyedVectors.load_word2vec_format(word2vec_path)
    print('Done')

    def get_word_vector(word):
        try:
            return model[word]
        except KeyError:
            return np.zeros(model.vector_size)

    return get_word_vector


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--word2vec_path', type=str, default='data/word2vec_from_glove_300.vec',
                        help='Word2Vec vectors file path')
    parser.add_argument('--fasttext_lib_path', type=str,
                        help='Path to fastText library')
    parser.add_argument('--fasttext_model_path', type=str, default=None,
                        help='Path to fastText model, if there is no such model, it will be downloaded automatically')
    parser.add_argument('--outfile', type=str, default='data/tmp.pkl',
                        help='Desired path to output pickle')
    parser.add_argument('--include_str', action='store_true',
                        help='Include string representation of words')

    parser.add_argument('data', type=str, help='Data json')
    args = parser.parse_args()

    if not args.outfile.endswith('.pkl'):
        args.outfile += '.pkl'

    print('Reading SQuAD data... ', end='')
    with open(args.data) as fd:
        samples = json.load(fd)
    print('Done!')

    print('Initiating CoreNLP service connection... ', end='')
    tokenize = CoreNLP_tokenizer()
    print('Done!')

    # Determine which model to use fasttext or word2vec (Glove)
    if args.fasttext_lib_path is not None:
        if not os.path.exists(args.fasttext_lib_path):
            raise ValueError('There is no fasttext library installed at ' + args.fasttext_lib_path)
        word_vector = initialize_fasttext(fasttext_lib_path=args.fasttext_lib_path,
                                          fasttext_model_path=args.fasttext_model_path)
    else:
        word_vector = word2vec(word2vec_path=args.word2vec_path)

    def parse_sample(context, question, answer_start, answer_end, **kwargs):
        inputs = []
        targets = []

        tokens, char_offsets = tokenize(context)
        try:
            answer_start = [s <= answer_start < e
                            for s, e in char_offsets].index(True)
            targets.append(answer_start)
            answer_end   = [s <= answer_end < e
                            for s, e in char_offsets].index(True)
            targets.append(answer_end)
        except ValueError:
            return None

        tokens = [unidecode(token) for token in tokens]

        context_vecs = [word_vector(token) for token in tokens]
        context_vecs = np.vstack(context_vecs).astype(np.float32)
        inputs.append(context_vecs)

        if args.include_str:
            context_str = [np.fromstring(token, dtype=np.uint8).astype(np.int32)
                           for token in tokens]
            context_str = pad_sequences(context_str, maxlen=25)
            inputs.append(context_str)

        tokens, char_offsets = tokenize(question)
        tokens = [unidecode(token) for token in tokens]

        question_vecs = [word_vector(token) for token in tokens]
        question_vecs = np.vstack(question_vecs).astype(np.float32)
        inputs.append(question_vecs)

        if args.include_str:
            question_str = [np.fromstring(token, dtype=np.uint8).astype(np.int32)
                            for token in tokens]
            question_str = pad_sequences(question_str, maxlen=25)
            inputs.append(question_str)

        return [inputs, targets]

    print('Parsing samples... ', end='')
    samples = [parse_sample(**sample) for sample in tqdm(samples)]
    samples = [sample for sample in samples if sample is not None]
    print('Done!')

    # Transpose
    def transpose(x):
        return map(list, zip(*x))

    data = [transpose(sample) for sample in transpose(samples)]

    print('Writing to file {}... '.format(args.outfile), end='')
    with open(args.outfile, 'wb') as fd:
        pickle.dump(data, fd, protocol=pickle.HIGHEST_PROTOCOL)
    print('Done!')
