import torch
from torch.utils.data import DataLoader
from torch.nn.utils.rnn import pad_sequence
import os

from tokenizer import SimpleTokenizer, CustomTokenizer
from dataset import SpeechesClassificationDataset, LanguageModelingDataset
from transformer import DecoderModel, EncoderModel,SendVariables
from utilities import Utilities
import torch.optim.lr_scheduler as lr_scheduler 
import sys


seed = 42

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

""" Hyperparameters to use for training to roughly match 
the numbers mentioned in the assignment description """
batch_size = 16  # Number of independent sequences  we will process in parallel
block_size = 32  # Maximum context length for predictions
learning_rate = 1e-3  # Learning rate for the optimizer
n_embd = 64  # Embedding dimension
n_head = 2  # Number of attention heads
n_layer = 4  # Number of transformer layers


eval_interval = 100  # How often to evaluate train and test perplexity during training
max_iters = 500 # For language modeling, we can process all the batches for the entire dataset, but that takes a while, so we'll limit it to 500 iterations. For batch size of 16 and block size of  32, this is roughly, this is  500 * 16 * 32 = 256000 tokens, SOTA LMs are trained on trillions of tokens, so this is a very small dataset.
eval_iters = 200  # Number of iterations to evaluate perplexity on the test set


## classifier training hyperparameters. It is a simple 1 hidden layer feedforward network, with input 
## size of 64, hidden size of 50 and output size of 3.

n_input = 64  # Input size for the classifier, should match the embedding size of the transformer
n_hidden = 100  # Hidden size for the classifier
n_output = 3  # Output size for the classifier, we have 3 classes
epochs_CLS = 15 # epochs for classifier training
vocab_size = 5755
def load_texts(directory):
    """
    This function loads all texts from the specified directory, ignoring any files with "test" in their name. The text is used for "training" the tokenizer. Since our tokenizer is simple, we don't need to do any training, but we still need to ignore the test data. 
    """

    texts = []
    files = os.listdir(directory)
    for filename in files: 
        if "test" in filename:  ## don't "read test files"
            continue
        with open(os.path.join(directory, filename), 'r', encoding='utf-8') as file:
            texts.append(file.read())
    return texts



def collate_batch(batch):
    """ Collate a batch of data into a single tensor with padding."""
    data, labels = zip(*batch)  # Separate the data and labels
    # Pad sequences to the fixed length
    padded_sequences = pad_sequence(data, batch_first=True, padding_value=0)
    padded_sequences = padded_sequences[:, :block_size]  # Truncate if longer
    # Add padding if shorter
    padded_sequences = torch.nn.functional.pad(padded_sequences, (0, max(0, block_size - padded_sequences.shape[1])), "constant", 0)
    labels = torch.stack(labels)  
    return padded_sequences, labels

def compute_classifier_accuracy(classifier, data_loader):
    """ Compute the accuracy of the classifier on the data in data_loader."""
    classifier.eval()
    total_correct = 0
    total_samples = 0
    with torch.no_grad():
        for X, Y in data_loader:
            X, Y = X.to(device), Y.to(device)
            outputs,_,_ = classifier(X)
            _, predicted = torch.max(outputs.data, 1)
            total_correct += (predicted == Y).sum().item()
            total_samples += Y.size(0)
        accuracy = (100 * total_correct / total_samples)
        classifier.train()
        return accuracy


def compute_perplexity(decoderLMmodel, data_loader, eval_iters=100):
    """ Compute the perplexity of the decoderLMmodel on the data in data_loader.
    Make sure to use the cross entropy loss for the decoderLMmodel.
    """
    decoderLMmodel.eval()
    losses= []
    for X, Y in data_loader:
        X, Y = X.to(device), Y.to(device)
        _,loss,_ = decoderLMmodel(X, Y) # your model should be computing the cross entropy loss
        losses.append(loss.item())
        #total_loss += loss.item()
        if len(losses) >= eval_iters: break


    losses = torch.tensor(losses)
    mean_loss = losses.mean()
    perplexity = torch.exp(mean_loss).item()  # Calculate perplexity as exp(mean loss)

    decoderLMmodel.train()
    return perplexity

def main():
    part = sys.argv[1]
    if part == "part1":
        part1()
    elif part == "part2":
        part2()
    elif part == "part3_1":
        part3_1()
    elif part == "part3_2":
        part3_2()
    else:
        print("Invalid part number. Use 'part1' or 'part2' or 'part3' as argument.")

def part1(pos_type_emb='absolute'):

    SendVariables(batch_size, block_size, learning_rate, n_embd, n_head, n_layer, vocab_size, n_hidden, n_output)

    print("Loading data and creating tokenizer ...")
    texts = load_texts('../speechesdataset')
    tokenizer = SimpleTokenizer(' '.join(texts)) # create a tokenizer from the data
    print("Vocabulary size is", tokenizer.vocab_size)

    #reading datasets

    train_CLS_dataset = SpeechesClassificationDataset(tokenizer, "../speechesdataset/train_CLS.tsv")
    train_CLS_loader = DataLoader(train_CLS_dataset, batch_size=batch_size,collate_fn=collate_batch,shuffle=True)
    test_CLS_dataset = SpeechesClassificationDataset(tokenizer, "../speechesdataset/test_CLS.tsv")
    test_CLS_loader = DataLoader(test_CLS_dataset, batch_size=batch_size,collate_fn=collate_batch,shuffle=True)

  
    #initialzing encoder model
    encoderModel = EncoderModel(pos_type_emb)
    encoderModel = encoderModel.to(device)
    # print the number of parameters in the model
    print(sum(p.numel() for p in encoderModel.parameters())/1e6, 'M parameters')

    # create a PyTorch optimizer
    optimizer = torch.optim.AdamW(encoderModel.parameters(), lr=learning_rate)
    loss_fn = torch.nn.CrossEntropyLoss()
     # for the classification  task, you will train for a fixed number of epochs like this:
    for epoch in range(epochs_CLS):
        losses = []
        for xb, yb in train_CLS_loader:
            xb, yb = xb.to(device), yb.to(device)
            # CLS training code here
            optimizer.zero_grad()
            outputs,_,_ = encoderModel(xb)
            loss = loss_fn(outputs,yb)
            losses.append(loss.item())
            loss.backward()
            optimizer.step()
        training_loss = sum(losses) / len(losses)
        accuracy_train = compute_classifier_accuracy(encoderModel, train_CLS_loader)
        accuracy_test = compute_classifier_accuracy(encoderModel, test_CLS_loader)
        print(f"Epoch {epoch+1}: Training Loss: {training_loss:.4f} || Accuracy on train set: {accuracy_train:.4f}% || Accuracy on test set: {accuracy_test:.2f}%")

    utilities = Utilities(tokenizer, encoderModel)
    utilities.sanity_check("To strengthen our middle class, we must give all our children the education they deserve, and all our workers the skills that they need to compete in a global economy.", block_size)

def part2(pos_type_emb='absolute'):

    SendVariables(batch_size, block_size, learning_rate, n_embd, n_head, n_layer, vocab_size, n_hidden, n_output)

    print("Loading data and creating tokenizer ...")
    texts = load_texts('../speechesdataset')
    tokenizer = SimpleTokenizer(' '.join(texts)) # create a tokenizer from the data
    print("Vocabulary size is", tokenizer.vocab_size)

    inputfile = "../speechesdataset/train_LM.txt"
    with open(inputfile, 'r', encoding='utf-8') as f:
        lmtrainText = f.read()
    train_LM_dataset = LanguageModelingDataset(tokenizer, lmtrainText,  block_size)
    train_LM_loader = DataLoader(train_LM_dataset, batch_size=batch_size, shuffle=True)

    inputfile = "../speechesdataset/test_LM_hbush.txt"
    with open(inputfile, 'r', encoding='utf-8') as f:
        lmtestText_hbush = f.read()
    test_LM_hbush_dataset = LanguageModelingDataset(tokenizer, lmtestText_hbush,  block_size)
    test_LM_hbush_loader = DataLoader(test_LM_hbush_dataset, batch_size=batch_size, shuffle=True)

    inputfile = "../speechesdataset/test_LM_obama.txt"
    with open(inputfile, 'r', encoding='utf-8') as f:
        lmtestText_obama = f.read()
    test_LM_obama_dataset = LanguageModelingDataset(tokenizer, lmtestText_obama,  block_size)
    test_LM_obama_loader = DataLoader(test_LM_obama_dataset, batch_size=batch_size, shuffle=True)

    inputfile = "../speechesdataset/test_LM_wbush.txt"
    with open(inputfile, 'r', encoding='utf-8') as f:
        lmtestText_wbush = f.read()
    test_LM_wbush_dataset = LanguageModelingDataset(tokenizer, lmtestText_wbush,  block_size)
    test_LM_wbush_loader = DataLoader(test_LM_wbush_dataset, batch_size=batch_size, shuffle=True)
    
    #initialzing decoder model
    decoderModel = DecoderModel(pos_type_emb)
    # print the number of parameters in the model
    print(sum(p.numel() for p in decoderModel.parameters())/1e6, 'M parameters')

    # create a PyTorch optimizer
    optimizer = torch.optim.AdamW(decoderModel.parameters(), lr=learning_rate)


    # for the language modeling task, you will iterate over the training data for a fixed number of iterations like this:
    for i, (xb, yb) in enumerate(train_LM_loader):
        if i >= max_iters:
            break
        xb, yb = xb.to(device), yb.to(device)
        if (i+1) % eval_interval == 0 or i == 0:
            perp_train = compute_perplexity(decoderModel, train_LM_loader)
            perp_test_hbush = compute_perplexity(decoderModel, test_LM_hbush_loader)
            perp_test_obama = compute_perplexity(decoderModel, test_LM_obama_loader)
            perp_test_wbush = compute_perplexity(decoderModel, test_LM_wbush_loader)
            print(f"iter: {i+1} || perp training: {perp_train:.4f} || perp test on hbush: {perp_test_hbush:.4f} || perp test on obama: {perp_test_obama:.4f} || perp test on wbush: {perp_test_wbush:.4f}")
            
        logits, loss,_ = decoderModel(xb, yb)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    utilities = Utilities(tokenizer, decoderModel)
    utilities.sanity_check("It is costly and politically difficult to continue this conflict.", block_size)
def part3_1():
    #Calling Classifiier training
    print("No positional Embedding Encoding used in Classifier")
    part1('NoPe')
    print('-------------------------------------------------------------------------------')
    print("Attention with Linear Positional Encoding used in Classifier")
    part1('AliBi')
    print('-------------------------------------------------------------------------------')
    print("No positional Embedding Encoding used in Language Modeling")
    part2('NoPe')
    print('-------------------------------------------------------------------------------')
    print("Attention with Linear Positional Encoding used in Language Modeling")
    part2('AliBi')
    print('-------------------------------------------------------------------------------')

def part3_2():
    epochs_CLS = 25
    n_head = 2
    n_layer = 8
    n_hidden = 2*n_embd
    block_size = 48

    print("Loading data and creating tokenizer ...")
    texts = load_texts('../speechesdataset')

    #tokenizer = SimpleTokenizer(' '.join(texts),max_vocab_size=3000) # create a tokenizer from the data
    tokenizer = CustomTokenizer(' '.join(texts),max_vocab_size=3000) # create a tokenizer from the data

    print("Vocabulary size is", tokenizer.vocab_size)
    vocab_size = tokenizer.vocab_size
    
    SendVariables(batch_size, block_size, learning_rate, n_embd, n_head, n_layer, vocab_size, n_hidden, n_output)

    #reading datasets

    train_CLS_dataset = SpeechesClassificationDataset(tokenizer, "../speechesdataset/train_CLS.tsv")
    train_CLS_loader = DataLoader(train_CLS_dataset, batch_size=batch_size,collate_fn=collate_batch,shuffle=True)
    test_CLS_dataset = SpeechesClassificationDataset(tokenizer, "../speechesdataset/test_CLS.tsv")
    test_CLS_loader = DataLoader(test_CLS_dataset, batch_size=batch_size,collate_fn=collate_batch,shuffle=True)

  
    #initialzing encoder model
    encoderModel = EncoderModel('absolute')
    encoderModel = encoderModel.to(device)
    # print the number of parameters in the model
    print(sum(p.numel() for p in encoderModel.parameters())/1e6, 'M parameters')

    # create a PyTorch optimizer
    optimizer = torch.optim.AdamW(encoderModel.parameters(), lr=learning_rate)

    # Initialize the scheduler
    scheduler = lr_scheduler.StepLR(optimizer,step_size=5, gamma=0.75)
    loss_fn = torch.nn.CrossEntropyLoss()
     # for the classification  task, you will train for a fixed number of epochs like this:
    for epoch in range(epochs_CLS):
        losses = []
        for xb, yb in train_CLS_loader:
            xb, yb = xb.to(device), yb.to(device)
            # CLS training code here
            optimizer.zero_grad()
            outputs,_,_ = encoderModel(xb)
            loss = loss_fn(outputs,yb)
            losses.append(loss.item())
            loss.backward()
            optimizer.step()

        scheduler.step()
        #print(optimizer.param_groups[0]['lr'])
        training_loss = sum(losses) / len(losses)
        accuracy_train = compute_classifier_accuracy(encoderModel, train_CLS_loader)
        accuracy_test = compute_classifier_accuracy(encoderModel, test_CLS_loader)
        print(f"Epoch {epoch+1}: Training Loss: {training_loss:.4f} || Accuracy on train set: {accuracy_train:.4f}% || Accuracy on test set: {accuracy_test:.2f}%")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <part>")
        sys.exit(1)


    main()
